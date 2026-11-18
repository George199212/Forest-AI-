#!/usr/bin/env python3
"""Sectors card-list FIXTURE from DB COPIES, read-only: the payload of GET /api/sectors/cards
(services/sector_cards.py — the same code the API runs), plus fixture-only parts:

  --with-kekava-fixture   the Ķekava EVAL_BBOX area as a card flagged _fixture_only (owner D3: never in the app)
  redaction               always: client/property names, surname, cadastral numbers (scripts/fixture_redaction.py);
                          the application itself always shows the full stored values (owner F3)

  python3 -I scripts/sector_cards_fixture.py --forest-db COPY --sat-db COPY --out tests/fixtures/sectors_ui/sector_cards.json \
      [--with-kekava-fixture] [--redact-terms-file /root/sectors_sandbox/redact_terms.txt]
"""
import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_VALID_PCT_DEFAULT = 60.0                                  # satellite_monitoring/config.py DEFAULTS["min_valid_pct"]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def kekava_card(sc_mod, sat_db, min_valid):
    sc = sc_mod.ro(sat_db)
    try:
        a = sc.execute("SELECT * FROM sat_monitored_areas WHERE source='EVAL_BBOX' AND active=1 ORDER BY id LIMIT 1").fetchone()
        if not a:
            return None
        a = dict(a)
        m = sc_mod.area_monitoring(sc, a, min_valid)
    finally:
        sc.close()
    m["link"] = "EVAL_BBOX"
    geom = json.loads(a["geometry_geojson"])
    ring = sc_mod.thin(geom["coordinates"][0]) if geom.get("type") == "Polygon" else None
    ext, bbox = sc_mod.extent_m(ring) if ring else (None, None)
    return {"id": "fixture-kekava", "_fixture_only": True, "name": a["name"], "status_text": None, "data_origin": None,
            "area_ha": a["area_ha"], "area_ha_source": "satellite_area", "created_at": a["added_at_utc"], "archived_at": None,
            "identifier": None, "provenance": {"provider": "EVAL_BBOX", "source_feature_id": a["source_ref"],
                                               "imported_at": a["added_at_utc"]},
            "boundary_plan_id": None, "ring": ring, "bbox": bbox, "extent_m": ext, "monitoring": m, "queued_job_id": None}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--forest-db", required=True)
    ap.add_argument("--sat-db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--with-kekava-fixture", action="store_true")
    ap.add_argument("--min-valid-pct", type=float, default=MIN_VALID_PCT_DEFAULT)
    ap.add_argument("--redact-terms-file", help="untracked terms file for scripts/fixture_redaction.py; client and "
                    "property names are also read from --forest-db. Redaction is always applied.")
    a = ap.parse_args(argv)
    for p in (a.forest_db, a.sat_db):
        if p.startswith("/root/forest_ai/data/") or p.startswith("/root/forest_ai_satellite_data/"):
            sys.exit("refusing to read a live DB path; use a .backup copy")
    sc_mod = _load("sector_cards", ROOT / "services" / "sector_cards.py")
    red = _load("fixture_redaction", ROOT / "scripts" / "fixture_redaction.py")
    payload = sc_mod.cards(a.forest_db, a.sat_db, a.min_valid_pct)
    if a.with_kekava_fixture:
        k = kekava_card(sc_mod, a.sat_db, a.min_valid_pct)
        if k:
            payload["sectors"].append(k)
    rules = red.compile_rules(red.load_terms(a.forest_db, a.redact_terms_file))
    doc = {"_captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "_source": "scripts/sector_cards_fixture.py = services/sector_cards.py on .backup copies (read-only); "
                      "client/property names, surname and cadastral numbers redacted (fixtures only)",
           "_note": "Shape of GET /api/sectors/cards. Cards with _fixture_only are Stage 1 fixtures (D3), never in the app.",
           "meta": payload["meta"], "sectors": red.redact_json(payload["sectors"], rules)}
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(doc['sectors'])} cards -> {a.out}")


if __name__ == "__main__":
    main()
