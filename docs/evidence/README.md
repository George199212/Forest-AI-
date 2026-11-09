# docs/evidence

Verification evidence (API responses, browser checks, screenshots, audit tables)
produced while building LVM GEO / VMD registration and the Forest Map.

The evidence files are **not in git** (`.gitignore`: `docs/evidence/*` except this
README). They stay on the production VPS under `/root/forest_ai/docs/evidence/`.
The documents in `docs/` that cite them stay valid as long as that folder is kept.

| folder | files | size | contents | cited by |
|---|---|---|---|---|
| `forest-map-20261107/` | 11 | 2.6 MB | Forest Map production activation: acceptance, architecture, overview build, sector overlay, implementation SHA-256, regression logs, 2 PNG screenshots | `docs/FOREST_MAP_20261107.md` |
| `forest-map-audit-20261107/` | 5 | 2.7 MB | Audit candidate (not activated): acceptance, data parity, sector audit, 2 PNG screenshots | `docs/FOREST_MAP_AUDIT_20261107.md` |
| `full-diagnostic-20261107/` | 11 | 112 KB | Catalogue health, geometry, indexes, integrity, query plans, preservation checks | `docs/LVM_VMD_FULL_DIAGNOSTIC_20261107.md` |
| `nationwide/` (+ `audit-01000950031/`) | 14 | 304 KB | data.gov.lv dataset metadata snapshots, VZD bulk and endpoint probes, cadastral audit table | `docs/NATIONWIDE_*.md` |
| `vmd-real-world-20261107/` | 36 | 7.0 MB | 20 `api-<cadastre>.json` responses, browser tests, quality report, 4 regional PNG previews, 6 Python evidence scripts | `docs/VMD_REAL_WORLD_TEST_20261107.md` |

All evidence is derived from public open data: VMD forest compartments (CC0-1.0) and
VZD cadastral parcels (CC-BY-4.0, attribution "Valsts zemes dienests"). It contains no
credentials. To archive it, copy the folder off the VPS as-is (for example with `tar`).
Do not add it to git history.
