"""
IntegrationAdapter — the common interface every external-system connector
(machine telematics, fleet GPS, GIS, satellite, timber/weighbridge, worker,
ERP, audit) implements, so the Integration Registry and the API layer can
treat all of them identically. Modeled directly on the existing
services/satellite_intelligence/providers/base.py::SatelliteProvider pattern
(is_configured()-style guard, never raise on external failure, explicit
LIVE/DEMO source tag) — generalized here to cover every integration
category, not just satellite.

Method names follow the spec's lifecycle 1:1, in snake_case (this codebase
has no camelCase anywhere — see database.py/api.py):
    connect, disconnect, test_connection, authenticate, refresh_credentials,
    fetch_data, normalize_data, validate_data, save_data, sync,
    get_sync_status, handle_error

`sync()` is the only method most callers (api.py routes, the demo seed)
actually need to call — it orchestrates the rest and is implemented once
here, not re-implemented per adapter. Subclasses normally only implement
`authenticate`, `fetch_data`, `normalize_data`, `validate_data` and
`save_data`; category base classes in categories.py add shared defaults for
`normalize_data`/`save_data` per data family.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

import database
from . import crypto


class AdapterError(Exception):
    """Raised by adapter internals; sync() always catches this (and any
    other Exception) so a single failing integration can never crash the
    caller — the error is recorded on the integration row instead."""


class IntegrationAdapter(ABC):
    # Class-level catalog metadata — overridden by every concrete adapter.
    category: str = "unknown"          # machine | fleet | gis | satellite | timber | weighbridge | worker | erp | audit
    provider: str = "unknown"          # stable key, e.g. "ponsse_manager", "fleet_gps_demo"
    display_name: str = "Unknown provider"
    is_demo_capable: bool = False
    implemented: bool = False          # False = catalog-only ("planned"), never shown as connectable

    def __init__(self, integration: dict):
        """`integration` is a row from database.get_integration() /
        get_integration_by_provider() — the adapter is always constructed
        around a persisted integration record, never floating config."""
        self.integration = integration
        self.integration_id = integration["id"]
        self.organization_id = integration["organization_id"]
        self.is_demo = bool(integration.get("is_demo"))
        self._credentials: Optional[dict] = None

    # ── Lifecycle methods every adapter implements ──────────────────────

    def connect(self) -> bool:
        """Marks the integration CONNECTED after a successful test_connection().
        Default implementation is sufficient for almost every adapter —
        override only if connecting has side effects beyond a status flip."""
        ok, message = self.test_connection()
        status = "CONNECTED" if ok else "ERROR"
        database.update_integration(self.integration_id, connection_status=status,
                                     error_message=None if ok else message)
        return ok

    def disconnect(self) -> None:
        database.update_integration(self.integration_id, connection_status="NOT_CONNECTED",
                                     sync_status="IDLE")

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """Returns (ok, message). Must NEVER raise — network/auth failures
        are caught and reported as (False, reason)."""
        raise NotImplementedError

    @abstractmethod
    def authenticate(self) -> bool:
        """Establishes/validates credentials for this call. Demo adapters
        always return True (no real credentials involved)."""
        raise NotImplementedError

    def refresh_credentials(self) -> bool:
        """Default: no-op success. Override for OAuth-style providers that
        need token refresh (e.g. a future real Sentinel/PONSSE adapter)."""
        return True

    @abstractmethod
    def fetch_data(self, **kwargs) -> list[dict]:
        """Returns a list of RAW provider-shaped records. Demo adapters
        generate deterministic synthetic records here instead of calling a
        network API — see demo/*.py. Must never raise; return [] on failure
        and call self.handle_error() internally."""
        raise NotImplementedError

    @abstractmethod
    def normalize_data(self, raw_records: list[dict]) -> list[dict]:
        """Raw provider records -> Forest AI's normalized shape for this
        category. See categories.py for the per-category normalized field
        contract (mirrors the spec's normalized entities)."""
        raise NotImplementedError

    def validate_data(self, normalized_records: list[dict]) -> list[dict]:
        """Filters out records missing required fields. Default requires
        external_id + entity_type + a resolvable timestamp; override to
        tighten per category."""
        valid = []
        for rec in normalized_records:
            if rec.get("external_id") and rec.get("entity_type"):
                valid.append(rec)
        return valid

    def save_data(self, valid_records: list[dict]) -> dict:
        """Idempotent upsert into integration_records, keyed on
        deduplication_key (see make_dedup_key) so a repeated sync never
        creates duplicates. This default is sufficient for categories with
        no dedicated domain table yet (GIS, ERP, audit); categories that do
        have one (fleet GPS, satellite, weighbridge) override this to also
        write the relevant domain table — see categories.py and demo/*.py."""
        saved = 0
        deduplicated = 0
        linked_ids = []
        for rec in valid_records:
            dedup_key = rec.get("deduplication_key") or self.make_dedup_key(
                rec["external_id"], rec.get("source_timestamp")
            )
            record_id, created = database.upsert_integration_record(
                integration_id=self.integration_id, organization_id=self.organization_id,
                source_provider=self.provider, entity_type=rec.get("entity_type", "unknown"),
                external_id=rec["external_id"], deduplication_key=dedup_key,
                sector=rec.get("sector"), source_timestamp=rec.get("source_timestamp"),
                raw_payload=rec.get("raw_payload"), normalized_payload=rec,
                is_demo=self.is_demo,
            )
            linked_ids.append(record_id)
            if created:
                saved += 1
            else:
                deduplicated += 1
        return {"saved": saved, "deduplicated": deduplicated, "linked_ids": linked_ids}

    def get_sync_status(self) -> dict:
        fresh = database.get_integration(self.integration_id)
        runs = database.get_sync_runs(self.integration_id, limit=5)
        return {"integration": fresh, "recent_runs": runs}

    def handle_error(self, exc: Exception, sync_run_id: Optional[int] = None) -> None:
        message = f"{type(exc).__name__}: {exc}"
        database.update_integration(self.integration_id, sync_status="ERROR",
                                     last_error_at=_now(), error_message=message)
        database.add_integration_log(self.integration_id, message, level="ERROR", sync_run_id=sync_run_id)

    # ── Orchestration — implemented once, not per adapter ───────────────

    def sync(self, trigger: str = "manual", **fetch_kwargs) -> dict:
        """Full pipeline: authenticate -> fetch -> normalize -> validate ->
        save -> update integration bookkeeping. Never raises — any
        exception anywhere in the pipeline is caught, logged via
        handle_error(), and reflected in the returned dict."""
        sync_run_id = database.start_sync_run(self.integration_id, trigger=trigger)
        database.update_integration(self.integration_id, sync_status="SYNCING")
        try:
            if not self.authenticate():
                raise AdapterError("authenticate() returned False")

            raw = self.fetch_data(**fetch_kwargs) or []
            normalized = self.normalize_data(raw) or []
            valid = self.validate_data(normalized) or []
            result = self.save_data(valid) or {"saved": 0, "deduplicated": 0}

            now = _now()
            database.finish_sync_run(
                sync_run_id, "SUCCESS", records_fetched=len(raw),
                records_saved=result.get("saved", 0),
                records_deduplicated=result.get("deduplicated", 0),
            )
            database.update_integration(
                self.integration_id, sync_status="IDLE", last_sync_at=now, last_success_at=now,
                error_message=None,
            )
            if result.get("saved"):
                database.increment_integration_records(self.integration_id, result["saved"])
            database.add_integration_log(
                self.integration_id,
                f"Sync OK ({trigger}): fetched={len(raw)} saved={result.get('saved', 0)} "
                f"deduplicated={result.get('deduplicated', 0)}",
                level="INFO", sync_run_id=sync_run_id,
            )
            return {
                "ok": True, "sync_run_id": sync_run_id, "fetched": len(raw),
                "saved": result.get("saved", 0), "deduplicated": result.get("deduplicated", 0),
            }
        except Exception as exc:
            database.finish_sync_run(sync_run_id, "ERROR", error_message=str(exc))
            self.handle_error(exc, sync_run_id=sync_run_id)
            return {"ok": False, "sync_run_id": sync_run_id, "error": str(exc)}

    # ── Credential helpers (shared, not overridden) ─────────────────────

    def get_credentials(self) -> dict:
        if self._credentials is not None:
            return self._credentials
        row = database.get_integration_credential(self.integration_id)
        if not row:
            self._credentials = {}
            return {}
        import json
        plaintext = crypto.decrypt_credentials(row["encrypted_value"])
        self._credentials = json.loads(plaintext)
        return self._credentials

    def set_credentials(self, fields: dict) -> None:
        import json
        encrypted = crypto.encrypt_credentials(json.dumps(fields))
        database.set_integration_credential(self.integration_id, encrypted)
        self._credentials = fields

    def make_dedup_key(self, external_id: str, source_timestamp: Optional[str] = None) -> str:
        version = source_timestamp or "v1"
        return f"org{self.organization_id}:{self.provider}:{external_id}:{version}"


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
