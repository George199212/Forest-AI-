# Known Bugs / Limitations

- Vehicle GPS route (History → Vehicles → click plate → map): the route is built only from
  manual GPS pings sent via the Telegram bot's "🚛 Vehicle GPS" flow, not from a continuous
  live track. Points appear only when a driver explicitly sends a location for that vehicle.

- `requirements.txt` is missing `python-multipart`. FastAPI refuses to start without it
  ("Form data requires python-multipart"). Production works only because the package is
  installed system-wide. A clean install from `requirements.txt` fails. Found 2026-10-13.
  **Fixed** (checked 2026-11-09): `python-multipart==0.0.32` is in `requirements.txt`.
- `install.sh` in the repo root is not a Forest AI file: it is the third-party installer of
  `DeusData/codebase-memory-mcp`. It does not install Forest AI. Found 2026-10-13; left in place
  pending the owner's decision. Still present (checked 2026-11-09).
- Before/after photo comparison (`services/photo_compare.py`): sector BIK-001, point P1 was
  marked "same place: yes" for two photos of different marker posts (different symbols,
  different path). False same-place match; 15 of 30 points also unmatched. Seen 2026-10-13
  on a screenshot, root cause not yet investigated.
  Mitigated 2026-10-13 (UI): default filter "Sakrītošās vietas" shows only pairs with both sides,
  same_place=yes, comparability not unsuitable and no reviewer decision against them; reviewer button
  "✗ Nav tā pati vieta" removes a false pair (decision + removed automatic findings kept in the event log).
  The model's same-place judgement itself is unchanged. Geometric matching (SIFT + RANSAC) was tested and
  cannot verify same place for forest photos taken from different positions (parallax), so it is not used.
- `bot.py` hardcodes the dashboard link as `http://164.90.188.136:8000` (3 places). A bot for
  a client instance would send users to the main dashboard. Still present (checked 2026-11-09).

- LVM GEO (fixed on `feature/lvm-geo-finish`, not deployed, 2026-11-10): clicking a compartment polygon to
  read its popup toggled its selection; clicking an off-page selected polygon removed it; a row click
  scrolled the page to the map; every toggle rebuilt the table. Live :8000 (frontend `fd3d2c6`) still has
  the polygon-click toggle until this branch is deployed.
- Forest Map (fixed on `feature/lvm-geo-finish`, not deployed, 2026-11-10): basemap switch only in the
  sidebar, below the fold; no control on the map.
- LVM GEO boundary rule (by design, not changed): compartments with a few cm² outside the VZD land unit
  are blocked as "Robežu neatbilstība" (e.g. 01000920499: 35 of 84 blocked, all < 1 m² outside).
  Needs a product decision on a tolerance.
- Sidebar language switches with the page on :8000: Latvian only while LVM GEO is open
  (`localizeGeodataNavigation`), English elsewhere; header time `lv-LV` only on LVM GEO. Found 2026-11-10.
- Pre-existing test failures on master with the real data catalogues (unrelated to this branch):
  `tests/test_vmd_production.py::test_actual_logged_no_match_reports_limited_source_coverage` (3 params) and
  `::test_official_outside_parcel_is_coverage_diagnostic_never_a_forest_match`. Found 2026-11-10.
- Forest Map on basemap "Karte" (fixed on `feature/forest-map-basemap-contrast`, not deployed, 2026-11-10): VMD
  compartment boundaries (`#74c484`, 1.1 px) were almost invisible on OSM's green woodland; VZD parcels and the
  grey GPS transition line were weak on white. Satellite was fine and is unchanged.
- No GPS session in the production DB has transitions or gaps yet (only session #32 has track points), so the
  white-casing style for them was checked with a clearly labelled synthetic sample only. Found 2026-11-10.

## Found 2026-11-13 (demo geo release)
- **Forest Map tile sizes (production :8000, pre-existing).** Same 108 tile requests gave byte-identical results on
  :8000 and the demo. Over the 600-feature / 400 KB target: Riga z14 VZD parcels 1290 features / 524,841 B; Riga z15
  parcels 644 / 285,423 B; Jelgava z14 parcels 960 / 372,022 B; DEMO-001 area z13 VMD compartments 702 / 346,243 B.
  Presence cells (z≤12) ≤ 37 KB. Code limits are `MAX_FEATURES=2000`, `MAX_TILE_BYTES=1_500_000`. Not fixed.
- **`GET /api/john-deere/status` writes on production :8000.** Every call without a valid session cookie inserts a
  `john_deere_sessions` row (and deletes expired ones first, so the table stays small). Read-only SELECT on the
  production DB, 2026-11-13 11:05 UTC: 1 row (created 2026-11-12 09:40 UTC, expired, no oauth_state); growth ≈ one
  row per browser per hour of Integrations use, one per call for cookie-less clients. Fixed only for review mode
  (`b6d3769`); production fix needs a separate OK.
- **Test environment:** `py7zr` is not installed (ingest-only dependency, `requirements-geodata-ingest.txt`), so all
  10 tests in `tests/test_nationwide_geodata.py` error at import. `tests/test_vmd_production.py` (8–9 tests) needs the
  regional VMD catalogue and `data/cadastre` at the repo-relative path. `tests/test_john_deere_sync.py::
  test_map_objects_and_protected_sync_routes` fails (no such table / unable to open database file).
- **30 order-dependent errors in `tests/test_integrations.py`** in the full suite; the file passes alone (30 passed).
  Same set on the base commit `66572fa`.
- **Route walking in tests:** FastAPI 0.136 wraps included routers in `_IncludedRouter`, so iterating `app.routes` for
  `APIRoute` misses them. `tests/test_review_mode.py::test_every_non_get_route_is_403` has that blind spot (non-GETs are
  still refused because the middleware is path-agnostic); `tests/review_no_writes.get_routes` recurses correctly.
- **:8003 is publicly reachable** (also 8000/8002/8004): uvicorn on 0.0.0.0, plain HTTP with Basic Auth, no reverse proxy,
  ufw inactive, iptables INPUT ACCEPT. The DigitalOcean cloud firewall is not visible from the server (no `doctl`);
  the demo journal shows external clients and scanners reaching :8003. Fix (TLS proxy, loopback bind, firewall) needs a
  separate OK.
