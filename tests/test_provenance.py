"""
Provenance tests (docs/demo-layer-plan.md, stage 1) — risks.data_origin / sectors.data_origin,
the risk_evidence table, and the demo resets that must never delete REAL rows and must keep
simulated-integration rows unless explicitly asked.

Run: python3 -m pytest tests/test_provenance.py -v

database.DB_NAME is read once, at the first import of `database`. test_integrations.py sets DB_PATH
at its import time, so this file must not import project modules at collection time (otherwise
that file would run against the wrong DB). Imports happen in the fixture; each test then points
database.DB_NAME at its own temp file (monkeypatch, restored afterwards). data/forest_ai.db is never used.
"""

import json
import os
import sqlite3
import tempfile

import pytest

_BOUNDARY = json.dumps([[56.90, 24.10], [56.90, 24.20], [56.95, 24.20], [56.95, 24.10]])
database = demo_scenarios = manager = risk_rules = None  # bound by the fixture


@pytest.fixture(autouse=True)
def db_path(tmp_path, monkeypatch):
    global database, demo_scenarios, manager, risk_rules
    if "DB_PATH" not in os.environ:  # running this file alone: never fall back to data/forest_ai.db
        boot = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        boot.close()
        os.environ["DB_PATH"] = boot.name
    os.environ.setdefault("INTEGRATION_CREDENTIALS_KEY", "pytest-test-key-not-for-production")
    os.environ.setdefault("DASHBOARD_USERNAME", "pytest")
    os.environ.setdefault("DASHBOARD_PASSWORD", "pytest")
    import database as _database
    from services import demo_scenarios as _demo_scenarios
    from services.integrations import manager as _manager, risk_rules as _risk_rules
    database, demo_scenarios, manager, risk_rules = _database, _demo_scenarios, _manager, _risk_rules
    path = str(tmp_path / "provenance.db")
    monkeypatch.setattr(database, "DB_NAME", path)
    database.init_db()
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO sectors (name, contractor, status, approved_volume, boundary_json, created_at) "
                 "VALUES ('SEC-1', 'C', 'Active', '100', ?, datetime('now'))", (_BOUNDARY,))
    conn.commit()
    conn.close()
    yield path


def _conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_legacy_risk(path, is_demo, rule_code):
    """A row as written before stage 1 (no data_origin)."""
    conn = _conn(path)
    cur = conn.execute("INSERT INTO risks (sector, risk_level, reason, created_at, is_demo, rule_code, status) "
                       "VALUES ('SEC-1', 'HIGH', 'legacy', datetime('now'), ?, ?, 'OPEN')", (is_demo, rule_code))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def _origin(path, rid):
    conn = _conn(path)
    row = conn.execute("SELECT data_origin FROM risks WHERE id=?", (rid,)).fetchone()
    conn.close()
    return row["data_origin"] if row else None


def _exists(path, table, where, params=()):
    conn = _conn(path)
    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]
    conn.close()
    return n


# ── Schema ───────────────────────────────────────────────────────────────────

def test_migration_is_idempotent_and_adds_schema(db_path):
    database.init_db()
    database.init_db()
    conn = _conn(db_path)
    risk_cols = {r["name"] for r in conn.execute("PRAGMA table_info(risks)")}
    sector_cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(sectors)")}
    ev_cols = [r["name"] for r in conn.execute("PRAGMA table_info(risk_evidence)")]
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(risk_evidence)")}
    conn.close()
    assert "data_origin" in risk_cols
    assert "data_origin" in sector_cols and sector_cols["data_origin"]["dflt_value"] == "'REAL'"
    assert ev_cols == ["id", "risk_id", "source_provider", "data_origin", "evidence_type", "summary",
                       "ref_table", "ref_id", "observed_at", "created_at"]
    assert "idx_risk_evidence_risk" in indexes


def test_backfill_maps_legacy_rows(db_path):
    real = _insert_legacy_risk(db_path, 0, "SECTOR_EXIT")
    manual = _insert_legacy_risk(db_path, 0, None)
    scenario = _insert_legacy_risk(db_path, 1, "EQUIPMENT_BREAKDOWN")
    simulated = _insert_legacy_risk(db_path, 1, "FLEET_SECTOR_EXIT")
    database.init_db()
    assert _origin(db_path, real) == "REAL"
    assert _origin(db_path, manual) == "REAL"
    assert _origin(db_path, scenario) == "DEMO_SCENARIO"
    assert _origin(db_path, simulated) == "SIMULATED_INTEGRATION"
    # existing and newly created sectors are REAL
    database.add_sector(name="SEC-2", contractor="C", status="", approved_volume="")
    assert _exists(db_path, "sectors", "COALESCE(data_origin,'') != 'REAL'") == 0


# ── Insert paths ─────────────────────────────────────────────────────────────

def test_insert_paths_set_origin(db_path):
    rid = database.add_incident("SEC-1", "HIGH", "x", entity_type="EMPLOYEE", entity_id=1, rule_code="SECTOR_EXIT")
    assert _origin(db_path, rid) == "REAL"
    database.add_risk("SEC-1", "MEDIUM", "manual")
    assert _exists(db_path, "risks", "reason='manual' AND data_origin='REAL'") == 1
    sc = database.add_incident("SEC-1", "HIGH", "scenario", rule_code="EQUIPMENT_BREAKDOWN")
    demo_scenarios._mark_demo(sc)
    assert _origin(db_path, sc) == "DEMO_SCENARIO"
    si = database.add_incident("SEC-1", "HIGH", "simulated", rule_code="FLEET_SECTOR_EXIT")
    risk_rules.database_update_is_demo(si)
    assert _origin(db_path, si) == "SIMULATED_INTEGRATION"
    explicit = database.add_incident("SEC-1", "LOW", "explicit", data_origin="SIMULATED_INTEGRATION",
                                     occurred_at="2026-10-12 08:00:00 UTC")
    conn = _conn(db_path)
    row = conn.execute("SELECT data_origin, occurred_at FROM risks WHERE id=?", (explicit,)).fetchone()
    conn.close()
    assert (row["data_origin"], row["occurred_at"]) == ("SIMULATED_INTEGRATION", "2026-10-12 08:00:00 UTC")


# ── Evidence ─────────────────────────────────────────────────────────────────

def test_risk_evidence_is_idempotent_including_null_refs(db_path):
    rid = database.add_incident("SEC-1", "HIGH", "x")
    a = database.add_risk_evidence(rid, "telegram_bot", "REAL", "GPS_TRACK", "29 punkti",
                                   ref_table="work_sessions", ref_id=32, observed_at="2026-10-11 05:24:27 UTC")
    b = database.add_risk_evidence(rid, "telegram_bot", "REAL", "GPS_TRACK", "29 punkti (atjaunots)",
                                   ref_table="work_sessions", ref_id=32, observed_at="2026-10-11 05:24:27 UTC")
    c = database.add_risk_evidence(rid, "external_warning", "REAL", "WARNING", "LVĢMC")
    d = database.add_risk_evidence(rid, "external_warning", "REAL", "WARNING", "LVĢMC (atjaunots)")
    assert a == b and c == d
    items = database.get_risk_evidence(rid)
    assert len(items) == 2
    assert {i["summary"] for i in items} == {"29 punkti (atjaunots)", "LVĢMC (atjaunots)"}


# ── Resets ───────────────────────────────────────────────────────────────────

def _one_of_each(path, rule_code="FLEET_SECTOR_EXIT"):
    real = database.add_incident("SEC-1", "HIGH", "real", rule_code=rule_code)
    scenario = database.add_incident("SEC-1", "HIGH", "scenario", rule_code=rule_code)
    demo_scenarios._mark_demo(scenario)
    simulated = database.add_incident("SEC-1", "HIGH", "simulated", rule_code=rule_code)
    risk_rules.database_update_is_demo(simulated)
    for rid in (real, scenario, simulated):
        database.add_risk_event(rid, "DETECTED", actor="test")
        database.add_risk_evidence(rid, "test", "REAL" if rid == real else "SIMULATED", "TEST", "t")
    return real, scenario, simulated


def test_global_demo_reset_keeps_real_and_simulated_by_default(db_path):
    real, scenario, simulated = _one_of_each(db_path)
    out = demo_scenarios.reset_demo()
    assert out["cleared_incidents"] == 1
    assert _origin(db_path, real) == "REAL"
    assert _origin(db_path, scenario) is None
    assert _origin(db_path, simulated) == "SIMULATED_INTEGRATION"
    assert _exists(db_path, "risk_events", "risk_id=?", (scenario,)) == 0
    assert _exists(db_path, "risk_evidence", "risk_id=?", (scenario,)) == 0
    assert _exists(db_path, "risk_evidence", "risk_id IN (?, ?)", (real, simulated)) == 2


def test_global_demo_reset_with_flag_also_clears_simulated_never_real(db_path):
    real, scenario, simulated = _one_of_each(db_path)
    out = demo_scenarios.reset_demo(include_simulated_integrations=True)
    assert out["cleared_incidents"] == 2
    assert _origin(db_path, real) == "REAL"
    assert _origin(db_path, scenario) is None and _origin(db_path, simulated) is None
    assert _exists(db_path, "risk_evidence", "risk_id=?", (real,)) == 1


def test_integration_reset_clears_only_its_simulated_rows(db_path):
    real, scenario, simulated = _one_of_each(db_path, rule_code="FLEET_SECTOR_EXIT")
    other = database.add_incident("SEC-1", "HIGH", "other category", rule_code="WEIGHBRIDGE_WAYBILL_MISMATCH")
    risk_rules.database_update_is_demo(other)
    row = manager.create_integration("fleet_gps_demo")
    out = manager.reset_demo(row["id"])
    assert out["deleted_incidents"] == 1
    assert _origin(db_path, simulated) is None
    assert _exists(db_path, "risk_evidence", "risk_id=?", (simulated,)) == 0
    assert _origin(db_path, real) == "REAL"
    assert _origin(db_path, scenario) == "DEMO_SCENARIO"
    assert _origin(db_path, other) == "SIMULATED_INTEGRATION"


# ── Client-instance cloning (Q14) ────────────────────────────────────────────

def test_clone_script_has_a_rule_for_risk_evidence():
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "clone_sector_instance.py")
    spec = importlib.util.spec_from_file_location("clone_sector_instance", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "risk_evidence" in [t for t, _ in mod.CHILD_RULES]
