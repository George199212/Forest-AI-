"""
Integration Layer — orchestration functions called by api.py's
/api/integrations/* routes. Mirrors the split services/demo_scenarios.py
already established: business logic lives in services/, api.py routes stay
thin (auth + validation + calling into here).
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import database
from . import registry, risk_rules


class IntegrationNotFound(Exception):
    pass


class ProviderUnknown(Exception):
    pass


def list_integrations(organization_id=1, category=None):
    rows = database.get_integrations(organization_id=organization_id, category=category)
    for row in rows:
        entry = registry.get_provider_entry(row["provider"])
        row["display_name"] = row.get("display_name") or (entry.display_name if entry else row["provider"])
        row["vendor"] = entry.vendor if entry else None
        row["has_credentials"] = bool(database.get_integration_credential(row["id"]))
    return rows


def list_catalog(organization_id=1):
    """Every provider (implemented + planned), each annotated with whether
    an integration row already exists for this org — this is what the
    Integrations page cards render (connected instances AND connectable/
    planned providers in one filterable grid)."""
    existing = {r["provider"]: r for r in database.get_integrations(organization_id=organization_id)}
    out = []
    for entry in registry.get_catalog():
        row = existing.get(entry.provider)
        out.append({
            "provider": entry.provider,
            "category": entry.category,
            "display_name": entry.display_name,
            "vendor": entry.vendor,
            "implemented": entry.implemented,
            "demo_available": entry.demo_available,
            "status_claim": entry.status_claim,
            "confirmed_customer_use": entry.confirmed_customer_use,
            "notes": entry.notes,
            "integration": row,
            # UI must render this instead of row.connection_status when no
            # row exists yet — a catalog entry with no integration row is
            # never "Connected".
            "display_status": (row["connection_status"] if row else
                                ("Demo" if entry.status_claim == "demo" else
                                 "Available" if entry.status_claim == "available" else "Planned")),
        })
    return out


def get_integration_or_raise(integration_id, organization_id=1):
    row = database.get_integration(integration_id, organization_id=organization_id)
    if not row:
        raise IntegrationNotFound(f"Integration {integration_id} not found")
    return row


def create_integration(provider, organization_id=1, is_demo=None, configuration=None,
                        display_name=None):
    entry = registry.get_provider_entry(provider)
    if not entry:
        raise ProviderUnknown(f"Unknown provider '{provider}'")
    if not entry.implemented:
        raise ProviderUnknown(
            f"Provider '{provider}' has no adapter implemented yet (catalog-only / planned) — "
            "cannot create a connectable integration for it."
        )
    if is_demo is None:
        is_demo = entry.status_claim == "demo"
    if is_demo and not entry.demo_available:
        raise ProviderUnknown(f"Provider '{provider}' has no demo mode available")
    integration_id = database.create_integration(
        organization_id=organization_id, category=entry.category, provider=provider,
        integration_type=entry.vendor, display_name=display_name or entry.display_name,
        is_demo=is_demo, configuration=configuration,
    )
    database.add_integration_log(integration_id, f"Integration created (provider={provider}, demo={is_demo})")
    return database.get_integration(integration_id)


def delete_integration(integration_id, organization_id=1):
    get_integration_or_raise(integration_id, organization_id)
    database.delete_integration(integration_id)


def test_connection(integration_id, organization_id=1):
    row = get_integration_or_raise(integration_id, organization_id)
    entry = registry.get_provider_entry(row["provider"])
    if not entry or not entry.implemented:
        return {"ok": False, "message": "No adapter implemented for this provider yet (catalog-only)."}
    adapter = registry.build_adapter(row)
    ok, message = adapter.test_connection()
    database.update_integration(integration_id, connection_status="CONNECTED" if ok else "ERROR",
                                 error_message=None if ok else message)
    database.add_integration_log(integration_id, f"test_connection: {message}",
                                  level="INFO" if ok else "ERROR")
    return {"ok": ok, "message": message}


def run_sync(integration_id, organization_id=1, trigger="manual"):
    row = get_integration_or_raise(integration_id, organization_id)
    entry = registry.get_provider_entry(row["provider"])
    if not entry or not entry.implemented:
        raise ProviderUnknown(f"No adapter implemented for provider '{row['provider']}' — cannot sync.")
    adapter = registry.build_adapter(row)
    return adapter.sync(trigger=trigger)


def get_logs(integration_id, organization_id=1, limit=100):
    get_integration_or_raise(integration_id, organization_id)
    return database.get_integration_logs(integration_id, limit=limit)


def get_records(integration_id, organization_id=1, limit=50):
    get_integration_or_raise(integration_id, organization_id)
    records = database.get_integration_records(integration_id, limit=limit)
    for r in records:
        if r.get("raw_payload_json"):
            r["raw_payload"] = json.loads(r["raw_payload_json"])
        if r.get("normalized_payload_json"):
            r["normalized_payload"] = json.loads(r["normalized_payload_json"])
    return records


def get_sync_history(integration_id, organization_id=1, limit=20):
    get_integration_or_raise(integration_id, organization_id)
    return database.get_sync_runs(integration_id, limit=limit)


def reset_demo(integration_id, organization_id=1):
    row = get_integration_or_raise(integration_id, organization_id)
    if not row.get("is_demo"):
        raise ValueError("reset-demo is only valid for demo integrations (is_demo=1)")
    deleted_records = database.delete_demo_integration_records(integration_id)
    deleted_weighbridge = database.delete_demo_weighbridge_records(integration_id)
    # Demo-created risk incidents, scoped to exactly this integration's
    # category's rule codes (never another demo integration's incidents —
    # e.g. resetting Fleet GPS must not also clear Weighbridge incidents)
    # and is_demo=1 only, exactly like services/demo_scenarios.py's own
    # reset_demo() never touches real operational risks.
    rule_codes = risk_rules.RULE_CODES_BY_CATEGORY.get(row["category"], [])
    deleted_incidents = 0
    if rule_codes:
        import sqlite3
        conn = sqlite3.connect(database.DB_NAME)
        cur = conn.cursor()
        placeholders = ",".join("?" * len(rule_codes))
        cur.execute(
            f"DELETE FROM risk_events WHERE risk_id IN "
            f"(SELECT id FROM risks WHERE is_demo=1 AND rule_code IN ({placeholders}))",
            rule_codes,
        )
        cur.execute(
            f"DELETE FROM risks WHERE is_demo=1 AND rule_code IN ({placeholders})",
            rule_codes,
        )
        deleted_incidents = cur.rowcount
        conn.commit()
        conn.close()
    database.update_integration(integration_id, records_received=0, sync_status="IDLE",
                                 last_sync_at=None, last_success_at=None, error_message=None)
    database.add_integration_log(
        integration_id,
        f"Demo data reset: records={deleted_records} weighbridge={deleted_weighbridge} "
        f"incidents={deleted_incidents}",
    )
    return {
        "ok": True, "deleted_records": deleted_records,
        "deleted_weighbridge_records": deleted_weighbridge, "deleted_incidents": deleted_incidents,
    }


def health():
    rows = database.get_integrations()
    by_status = {}
    for r in rows:
        by_status[r["connection_status"]] = by_status.get(r["connection_status"], 0) + 1
    stale_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
    stale = [r["id"] for r in rows if r.get("last_success_at") is None and r["connection_status"] == "CONNECTED"]
    return {
        "total_integrations": len(rows),
        "by_connection_status": by_status,
        "connected_without_successful_sync": stale,
    }


def handle_webhook(provider: str, raw_body: bytes, signature_header: str = None,
                    webhook_secret: str = None):
    """Signature verification (HMAC-SHA256, GitHub/Stripe-style) + replay
    protection via integration_webhook_events.payload_hash UNIQUE. Callers
    (api.py) pass the raw request body and the provider's configured
    secret — never trust a webhook whose signature doesn't match when a
    secret is configured."""
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    signature_valid = None
    if webhook_secret:
        import hmac
        expected = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        provided = (signature_header or "").replace("sha256=", "")
        signature_valid = hmac.compare_digest(expected, provided)
        if not signature_valid:
            return {"ok": False, "reason": "invalid_signature"}

    integration = database.get_integration_by_provider(provider)
    event_id, is_new = database.record_webhook_event(
        provider, payload_hash, integration_id=integration["id"] if integration else None,
        signature_valid=signature_valid,
    )
    if not is_new:
        return {"ok": True, "duplicate": True, "event_id": event_id}

    # Stage 1: webhook payloads are recorded and deduplicated but not yet
    # routed into a specific adapter's normalize/save pipeline (no
    # implemented adapter currently accepts inbound webhooks — the three
    # demo adapters are polling-only). Marking PROCESSED here reflects
    # that the event was durably logged, not that domain data was written.
    database.mark_webhook_processed(event_id, status="PROCESSED")
    if integration:
        database.add_integration_log(integration["id"], f"Webhook received from {provider} (hash={payload_hash[:12]})")
    return {"ok": True, "duplicate": False, "event_id": event_id}
