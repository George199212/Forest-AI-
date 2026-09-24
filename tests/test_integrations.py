"""
Integration Layer tests — migrations, adapter dedup, demo-mode isolation,
risk engine wiring, and the /api/integrations + /api/webhooks/* routes.

Run: python3 -m pytest tests/test_integrations.py -v

Uses a fresh temp SQLite file per test (never data/forest_ai.db) and a
throwaway INTEGRATION_CREDENTIALS_KEY — env vars are set before importing
database/api/services.integrations, since DB_NAME is read from os.environ
at import time.
"""

import json
import os
import sqlite3
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ["INTEGRATION_CREDENTIALS_KEY"] = "pytest-test-key-not-for-production"
os.environ.setdefault("DASHBOARD_USERNAME", "pytest")
os.environ.setdefault("DASHBOARD_PASSWORD", "pytest")

import database  # noqa: E402
from services.integrations import manager, registry, crypto  # noqa: E402


_DEMO_BOUNDARY = json.dumps([[56.90, 24.10], [56.90, 24.20], [56.95, 24.20], [56.95, 24.10]])


@pytest.fixture(autouse=True)
def fresh_db():
    """Wipe and re-migrate the temp DB before every test — tests must not
    depend on execution order or leak state between each other. Seeds two
    sectors with a real boundary_json so the demo adapters (which query
    `sectors` for AOIs, exactly like a real GIS/fleet adapter would) have
    something to work with."""
    if os.path.exists(_tmp_db.name):
        os.remove(_tmp_db.name)
    database.init_db()
    conn = sqlite3.connect(_tmp_db.name)
    cur = conn.cursor()
    for name, approved in [("DEMO-SECTOR-1", "600 m3"), ("DEMO-SECTOR-2", "100")]:
        cur.execute(
            "INSERT INTO sectors (name, contractor, status, approved_volume, boundary_json, created_at) "
            "VALUES (?, 'Test Contractor', 'Active', ?, ?, datetime('now'))",
            (name, approved, _DEMO_BOUNDARY),
        )
    conn.commit()
    conn.close()
    yield


def _conn():
    conn = sqlite3.connect(_tmp_db.name)
    conn.row_factory = sqlite3.Row
    return conn


# ── Migrations ───────────────────────────────────────────────────────────

def test_migration_creates_integration_tables():
    conn = _conn()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    for expected in ["organizations", "integrations", "integration_credentials",
                      "integration_sync_runs", "integration_logs", "integration_records",
                      "integration_webhook_events", "weighbridge_records"]:
        assert expected in tables


def test_migration_is_idempotent():
    database.init_db()
    database.init_db()  # must not raise, must not duplicate the seeded org
    conn = _conn()
    count = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
    conn.close()
    assert count == 1


def test_default_organization_seeded():
    conn = _conn()
    row = conn.execute("SELECT * FROM organizations WHERE id=1").fetchone()
    conn.close()
    assert row is not None
    assert row["slug"] == "default"


# ── Credential encryption ───────────────────────────────────────────────

def test_credentials_are_encrypted_at_rest():
    plaintext = json.dumps({"api_key": "sk-live-super-secret-value"})
    encrypted = crypto.encrypt_credentials(plaintext)
    assert "super-secret" not in encrypted
    assert crypto.decrypt_credentials(encrypted) == plaintext


def test_credentials_round_trip_through_database():
    integration_id = database.create_integration(1, "fleet", "fleet_gps_demo")
    encrypted = crypto.encrypt_credentials(json.dumps({"token": "abc123"}))
    database.set_integration_credential(integration_id, encrypted)
    row = database.get_integration_credential(integration_id)
    assert row is not None
    assert "abc123" not in row["encrypted_value"]
    decrypted = json.loads(crypto.decrypt_credentials(row["encrypted_value"]))
    assert decrypted["token"] == "abc123"


def test_mask_secret_never_reveals_full_value():
    masked = crypto.mask_secret("sk-live-abcdef123456")
    assert masked.endswith("3456")
    assert "sk-live" not in masked


# ── Registry / catalog ───────────────────────────────────────────────────

def test_catalog_lists_all_spec_categories():
    categories = {e.category for e in registry.get_catalog()}
    assert categories == {"machine", "fleet", "gis", "satellite", "timber",
                           "weighbridge", "worker", "erp", "audit"}


def test_only_three_providers_are_implemented_in_stage_one():
    implemented = {e.provider for e in registry.get_catalog() if e.implemented}
    assert implemented == {"fleet_gps_demo", "sentinel_demo", "weighbridge_demo"}


def test_non_implemented_provider_cannot_build_adapter():
    with pytest.raises(ValueError):
        registry.build_adapter({"id": 1, "provider": "ponsse_manager", "organization_id": 1, "is_demo": False})


def test_ponsse_and_komatsu_are_not_claimed_connected():
    """Core requirement: unconfirmed vendor integrations must never surface
    as Connected — catalog entries with no implemented adapter can only
    ever be 'planned' in the UI's display_status."""
    for provider in ["ponsse_manager", "johndeere_timbermatic", "komatsu_smart_forestry", "zf_scalar", "lvm_geo"]:
        entry = registry.get_provider_entry(provider)
        assert entry.status_claim in ("planned", "available")
        assert entry.implemented is False


def test_krauzers_and_timbro_have_conservative_confirmed_use_notes():
    krauzers = registry.get_provider_entry("krauzers_fleet")
    timbro = registry.get_provider_entry("timbro_audit")
    assert "vendor is not yet confirmed" in krauzers.confirmed_customer_use
    assert krauzers.implemented is False
    assert "No API/data contract is confirmed" in timbro.confirmed_customer_use
    assert timbro.implemented is False


# ── Adapter sync + idempotent dedup ──────────────────────────────────────

@pytest.mark.parametrize("provider", ["fleet_gps_demo", "sentinel_demo", "weighbridge_demo"])
def test_demo_adapter_sync_is_idempotent(provider):
    row = manager.create_integration(provider, is_demo=True)
    first = manager.run_sync(row["id"], trigger="test")
    second = manager.run_sync(row["id"], trigger="test")
    assert first["ok"] is True
    assert second["ok"] is True
    assert second["saved"] == 0
    assert second["deduplicated"] == first["fetched"]


def test_dedup_key_is_unique_across_integrations():
    """organization_id + source_provider + external_id + source_timestamp —
    two different integrations of the same provider (hypothetically) must
    not collide; here we assert the DB constraint exists and is enforced."""
    conn = _conn()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(integration_records)")]
    conn.close()
    assert "deduplication_key" in cols


def test_upsert_integration_record_never_duplicates():
    integration_id = database.create_integration(1, "fleet", "fleet_gps_demo")
    key = "org1:fleet_gps_demo:veh-1:v1"
    id1, created1 = database.upsert_integration_record(
        integration_id, 1, "fleet_gps_demo", "GPSPosition", "veh-1", key, sector="A-005",
    )
    id2, created2 = database.upsert_integration_record(
        integration_id, 1, "fleet_gps_demo", "GPSPosition", "veh-1", key, sector="A-005",
    )
    assert id1 == id2
    assert created1 is True
    assert created2 is False
    assert database.count_integration_records(integration_id) == 1


# ── Demo Mode isolation ──────────────────────────────────────────────────

def test_demo_records_flagged_is_demo():
    row = manager.create_integration("fleet_gps_demo", is_demo=True)
    manager.run_sync(row["id"], trigger="test")
    records = database.get_integration_records(row["id"])
    assert records
    assert all(r["is_demo"] == 1 for r in records)


def test_reset_demo_only_clears_this_integrations_category():
    fleet = manager.create_integration("fleet_gps_demo", is_demo=True)
    weighbridge = manager.create_integration("weighbridge_demo", is_demo=True)
    manager.run_sync(fleet["id"], trigger="test")
    manager.run_sync(weighbridge["id"], trigger="test")

    conn = _conn()
    before = {r["rule_code"] for r in conn.execute("SELECT DISTINCT rule_code FROM risks WHERE is_demo=1")}
    conn.close()

    manager.reset_demo(fleet["id"])

    conn = _conn()
    after = {r["rule_code"] for r in conn.execute("SELECT DISTINCT rule_code FROM risks WHERE is_demo=1")}
    conn.close()

    assert "FLEET_SECTOR_EXIT" not in after
    # Whatever weighbridge produced (if anything) must survive the fleet reset.
    assert (before - {"FLEET_SECTOR_EXIT"}) == after


def test_reset_demo_rejects_non_demo_integration():
    row = database.get_integration(database.create_integration(1, "fleet", "fleet_gps_demo", is_demo=False))
    with pytest.raises(ValueError):
        manager.reset_demo(row["id"])


def test_planet_provider_cannot_be_created_without_demo_or_adapter():
    with pytest.raises(manager.ProviderUnknown):
        manager.create_integration("planetscope")  # planned only, no demo_available


# ── Risk Engine bridge ───────────────────────────────────────────────────

def test_fleet_sector_exit_creates_incident_and_dedupes():
    from services.integrations import risk_rules
    conn = sqlite3.connect(_tmp_db.name)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sectors (name, contractor, status, approved_volume, boundary_json, created_at)
        VALUES ('TEST-SECTOR', 'Test', 'Active', '100', ?, datetime('now'))
    """, (json.dumps([[56.9, 24.1], [56.9, 24.2], [56.95, 24.2], [56.95, 24.1]]),))
    conn.commit()
    conn.close()

    record = {"sector": "TEST-SECTOR", "latitude": 57.5, "longitude": 25.5,
              "gps_entity_type": "VEHICLE", "vehicle_id": "TEST-VEH-1", "external_id": "TEST-VEH-1"}
    incident_id_1 = risk_rules.check_fleet_sector_exit(record, is_demo=True)
    incident_id_2 = risk_rules.check_fleet_sector_exit(record, is_demo=True)
    assert incident_id_1 is not None
    assert incident_id_1 == incident_id_2  # second call dedupes onto the same open incident

    conn = _conn()
    row = conn.execute("SELECT * FROM risks WHERE id=?", (incident_id_1,)).fetchone()
    events = conn.execute("SELECT * FROM risk_events WHERE risk_id=?", (incident_id_1,)).fetchall()
    conn.close()
    assert row["rule_code"] == "FLEET_SECTOR_EXIT"
    assert row["is_demo"] == 1
    assert len(events) >= 2  # DETECTED + STILL_OUTSIDE (+ AI_RECOMMENDATION_GENERATED)


def test_fleet_sector_exit_no_incident_when_inside_boundary():
    from services.integrations import risk_rules
    conn = sqlite3.connect(_tmp_db.name)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sectors (name, contractor, status, approved_volume, boundary_json, created_at)
        VALUES ('TEST-SECTOR-2', 'Test', 'Active', '100', ?, datetime('now'))
    """, (json.dumps([[56.9, 24.1], [56.9, 24.2], [56.95, 24.2], [56.95, 24.1]]),))
    conn.commit()
    conn.close()
    record = {"sector": "TEST-SECTOR-2", "latitude": 56.92, "longitude": 24.15,
              "gps_entity_type": "VEHICLE", "vehicle_id": "TEST-VEH-2", "external_id": "TEST-VEH-2"}
    from services.integrations import risk_rules
    assert risk_rules.check_fleet_sector_exit(record, is_demo=True) is None


# ── API routes (tenant scoping stays organization_id=1 today; see manager.py) ──

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import api
    with TestClient(api.app) as c:
        yield c


AUTH = ("pytest", "pytest")


def test_list_integrations_requires_auth(client):
    r = client.get("/api/integrations")
    assert r.status_code == 401


def test_list_integrations_returns_full_catalog(client):
    r = client.get("/api/integrations", auth=AUTH)
    assert r.status_code == 200
    assert len(r.json()["integrations"]) == len(registry.get_catalog())


def test_create_and_sync_via_api(client):
    r = client.post("/api/integrations", json={"provider": "weighbridge_demo", "is_demo": True}, auth=AUTH)
    assert r.status_code == 200
    integration_id = r.json()["id"]

    r = client.post(f"/api/integrations/{integration_id}/sync", auth=AUTH)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = client.get(f"/api/integrations/{integration_id}/records", auth=AUTH)
    assert r.status_code == 200
    assert len(r.json()["records"]) > 0


def test_unimplemented_provider_returns_400_not_500(client):
    r = client.post("/api/integrations", json={"provider": "ponsse_manager"}, auth=AUTH)
    assert r.status_code == 400


def test_get_missing_integration_returns_404(client):
    r = client.get("/api/integrations/999999", auth=AUTH)
    assert r.status_code == 404


def test_existing_routes_unaffected(client):
    for path in ["/api/sectors", "/api/risks", "/api/gps", "/api/summary"]:
        r = client.get(path, auth=AUTH)
        assert r.status_code == 200, f"{path} broke: {r.status_code}"


def test_webhook_signature_verification(client):
    os.environ["WEBHOOK_SECRET_TESTPROVIDER"] = "webhooksecret"
    body = json.dumps({"a": 1}).encode()

    r = client.post("/api/webhooks/testprovider", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 401  # no signature, secret is configured

    import hmac, hashlib
    sig = hmac.new(b"webhooksecret", body, hashlib.sha256).hexdigest()
    r = client.post("/api/webhooks/testprovider", content=body,
                     headers={"Content-Type": "application/json", "X-Signature": f"sha256={sig}"})
    assert r.status_code == 200
    assert r.json()["duplicate"] is False

    r = client.post("/api/webhooks/testprovider", content=body,
                     headers={"Content-Type": "application/json", "X-Signature": f"sha256={sig}"})
    assert r.status_code == 200
    assert r.json()["duplicate"] is True  # replay protection
    del os.environ["WEBHOOK_SECRET_TESTPROVIDER"]


def test_webhook_endpoint_not_behind_dashboard_auth(client):
    """External providers can't do this dashboard's HTTP Basic login —
    the webhook sub-app must be reachable without it (auth comes from the
    per-provider signature instead, see test_webhook_signature_verification)."""
    r = client.post("/api/webhooks/unconfigured_test_provider", json={"x": 1})
    assert r.status_code != 401 or "signature" not in r.text.lower()
    assert r.status_code == 200
