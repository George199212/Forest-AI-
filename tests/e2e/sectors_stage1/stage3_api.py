#!/usr/bin/env python3
"""Stage 3 API checks on the 127.0.0.1:8010 SANDBOX (DB copies, test-only auth) — never production.

1. LVM GEO registration on a copy (prompt §9, verify only): cadastral search → import ONE unregistered compartment →
   the sector appears in /api/sectors/cards ("Netiek monitorēts"), /api/objects and Meža karte with IDENTICAL geometry
   (coordinates compared, not screenshots); a second identical submit creates no duplicate.
2. 1,000 sectors: a separate .backup copy padded with synthetic sectors → services.sector_cards.cards() timing + size.

usage: python3 -I stage3_api.py   (prints a JSON report; names/identifiers of real sectors are not printed)
"""
import base64
import importlib.util
import json
import random
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

SB = Path("/root/sectors_sandbox")
BASE = "http://127.0.0.1:8010"
USER, PASS = SB.joinpath(".sandbox_auth").read_text().strip().split("\n")
AUTH = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()
COPY = SB / "data" / "forest_ai.db"
ROOT = Path(__file__).resolve().parents[3]


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Authorization": AUTH, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None


def rings_equal(a, b, tol=1e-9):
    return len(a) == len(b) and all(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol for p, q in zip(a, b))


def registration():
    out = {}
    c = sqlite3.connect(f"file:{COPY}?mode=ro", uri=True)
    kad = c.execute("SELECT json_extract(source_properties,'$.kadastrs') FROM geodata_sources WHERE sector_id=81").fetchone()[0]
    registered = {r[0] for r in c.execute("SELECT source_feature_id FROM geodata_sources")}
    n_before = c.execute("SELECT COUNT(*) FROM sectors").fetchone()[0]
    c.close()
    st, res = call("GET", f"/api/geodata/vmd/cadastre?kadastrs={kad}")
    out["search_http"] = st
    free = [f for f in res["features"] if f["id"] not in registered and f["properties"].get("import_status") == "READY"]
    out["search_features"], out["unregistered"] = len(res["features"]), len(free)
    feat = free[0]
    body = {"feature_ids": [feat["id"]], "dataset_version": res["dataset_version"], "cadastral_designation": kad,
            "sector_name": "STAGE3-SANDBOX-REG", "responsible_first_name": "Sandbox", "responsible_last_name": "Test",
            "dry_run": False, "confirmed": True}
    st1, r1 = call("POST", "/api/geodata/vmd/import-selected", body)
    st2, r2 = call("POST", "/api/geodata/vmd/import-selected", body)          # double submit
    out["import_http"], out["second_import_http"] = st1, st2
    out["second_import_summary"] = {k: r2.get(k) for k in ("created", "skipped", "state", "detail") if isinstance(r2, dict) and k in r2}
    c = sqlite3.connect(f"file:{COPY}?mode=ro", uri=True)
    rows = c.execute("SELECT s.id, s.boundary_json FROM sectors s JOIN geodata_sources g ON g.sector_id=s.id "
                     "WHERE g.source_feature_id=?", (feat["id"],)).fetchall()
    out["sectors_for_feature"] = len(rows)                                     # 1 = no duplicate
    out["sectors_added"] = c.execute("SELECT COUNT(*) FROM sectors").fetchone()[0] - n_before
    c.close()
    if not rows:
        return out
    sid, bj = rows[0]
    stored = [[float(p[1]), float(p[0])] for p in json.loads(bj)]            # [lat,lon] → [lon,lat]
    _, card = call("GET", f"/api/sectors/cards/{sid}")
    _, cards = call("GET", "/api/sectors/cards")
    in_list = [x for x in cards["sectors"] if x["id"] == sid]
    out["card_in_list"] = bool(in_list)
    out["card_status_fields"] = {"monitoring": card["sector"]["monitoring"], "queued_job_id": card["sector"]["queued_job_id"]}
    out["card_ring_equals_stored"] = rings_equal(card["sector"]["ring"], stored) if len(stored) <= 64 else "thinned (display only)"
    _, fm = call("GET", "/api/geodata/forest-map/sectors")
    f = [x for x in fm["features"] if x["properties"]["id"] == sid]
    out["forest_map_feature"] = bool(f)
    if f:
        out["forest_map_ring_equals_stored"] = rings_equal([list(p) for p in f[0]["geometry"]["coordinates"][0]], stored)
    _, objs = call("GET", "/api/objects")
    out["in_objects"] = any(s.get("name") == "STAGE3-SANDBOX-REG" for g in objs for s in g.get("sectors", []))
    _, det = call("GET", "/api/sectors/STAGE3-SANDBOX-REG")
    out["detail_boundary_equals_stored"] = json.loads(det["sector"]["boundary_json"]) == json.loads(bj)
    return out


def thousand():
    perf = SB / "perf_1000"
    perf.mkdir(exist_ok=True)
    dst = perf / "forest_ai.db"
    if dst.exists():
        dst.unlink()
    subprocess.run(["sqlite3", str(COPY), f".backup '{dst}'"], check=True)
    c = sqlite3.connect(dst)
    base = c.execute("SELECT boundary_json, area_ha FROM sectors WHERE id=81").fetchone()
    pts = json.loads(base[0])
    n = c.execute("SELECT COUNT(*) FROM sectors").fetchone()[0]
    rnd = random.Random(7)
    for i in range(1000 - n):
        dx, dy = rnd.uniform(-1.5, 1.5), rnd.uniform(-0.8, 0.8)
        ring = [[p[0] + dy, p[1] + dx] for p in pts]
        c.execute("INSERT INTO sectors(name, boundary_json, area_ha, organization_id, data_origin) VALUES (?,?,?,1,'SIMULATED')",
                  (f"PERF-{i:04d}", json.dumps(ring), base[1]))
    c.commit()
    total = c.execute("SELECT COUNT(*) FROM sectors").fetchone()[0]
    c.close()
    spec = importlib.util.spec_from_file_location("sector_cards", ROOT / "services" / "sector_cards.py")
    sc = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc)
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        p = sc.cards(str(dst), str(SB / "data" / "satellite.db"), 60.0)
        times.append(round((time.perf_counter() - t0) * 1000))
    size = len(json.dumps(p, ensure_ascii=False).encode())
    (perf / "cards_1000.json").write_text(json.dumps(p, ensure_ascii=False))
    return {"sectors": total, "cards_ms_3_runs": times, "payload_bytes": size}


if __name__ == "__main__":
    print(json.dumps({"registration_on_copy": registration(), "thousand_sectors": thousand()}, indent=1, default=str))
