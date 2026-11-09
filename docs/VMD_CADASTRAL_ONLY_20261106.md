# Exact cadastral compartment registration — 2026-11-06

This supersedes the earlier three-mode workflow. The live page is **http://164.90.188.136:8000/#lvm-geodata**, visible frontend version **geo-7b0f7def4aa9**.

## Scope implemented

The registration page now offers only one discovery path: an exact **11-digit cadastral land-unit designation**. Map-area, territory drawing/upload/loading, prefix searching, extra filters, complete-search scope controls and WMS browsing controls were removed from this page. Existing saved data and legacy backend APIs were retained for compatibility; no territories, sectors or datasets were deleted.

The existing Esri World Imagery basemap is preserved. Its tile URL, service metadata URL, attribution, zoom settings, Leaflet layer implementation and error fallback remain the same. The only basemap behavior change is selecting this existing satellite layer by default once available. No satellite-map replacement or redesign was performed; the existing workflow stylesheet and map layout were retained. Switching between the existing map bases remains available.

No Sentinel-1/2 archive, observation ingestion, change detection or new risk logic was implemented. Existing satellite observation/provider, Deere, geofencing and bot files matched the protected pre-change hashes (19 files checked).

## Exact search and geometry

The page calls authenticated GET `/api/geodata/vmd/cadastre?kadastrs=40940020002`. This registration endpoint requires exactly eleven ASCII digits, rejects missing/short/long/formatted/letter inputs with 422, and always searches `compartments.kadastrs` by equality. It never falls back to prefix, substring, property-number, OBJECTID or spatial matching. The UI also validates before requesting; it does not silently truncate overlong input.

`kadastrs` is the VMD land-unit designation; `kvart` and `nog` are quarter/compartment; `objectid` is the source feature identifier. The source mapping and the ten real records for `40940020002` remain documented in `docs/VMD_CADASTRAL_AUDIT_40940020002.md`.

All matching source polygons are represented by their genuine indexed geometry. The server now returns an aggregate bounds value over **all matching records**, allowing automatic zoom without downloading every page. The page preserves selection across pagination within one designation and clears it when a different successful designation is loaded. Polygon clicks select/deselect; rows focus their exact polygons; checkboxes and selected counts/area share the same state. “Atlasīt visus” explicitly means the current page. No boundary simplification or raster-derived boundary was introduced.

The UI rejects a response containing a cadastral designation inconsistent with the exact request. Real browser geometry verification compared all ten Leaflet geometries, at full coordinate precision, with the independently audited normalized source geometry. Original source EPSG:10306 geometry remains preserved alongside normalized EPSG:4326 geometry; the existing datum limitations are not presented as legal cadastral survey accuracy.

## Registration and persistence

The existing `/api/geodata/vmd/import-selected` API and ordinary Forest AI sector storage are reused. Preview shows the server-validated target client, count, hectares, geometry validity and duplicates. Confirmation retains exactly the reviewed source IDs/version/client metadata. The backend reloads source geometry, applies transactions/duplicate constraints and preserves native geometry, CRS, IDs, attributes, dataset version and provenance. Existing sectors are never overwritten by registration.

Registration invalidates the existing main-map cache so the resulting sectors appear in the ordinary map. No GPS observations, machinery positions, satellite observations or risk events are fabricated.

## Tests actually performed

- **256 Python tests passed** with the documented test-only same-thread ASGI workaround required by this executor. Includes strict endpoint/auth checks, no-match behavior, full source bounds, source geometry/CRS, transaction rollback, duplicate prevention, persistence, client isolation and Deere regressions.
- **27 JavaScript checks passed**: focused registration UI 8, existing WMS 9, module delivery/dispatch 3 and retained legacy local component 7. The focused UI tests cover strict input, genuine geometry rendering, automatic fit, map selection/deselection, pagination, new-search clearing and frozen registration intent.
- Python and inline/module JavaScript syntax and `git diff --check` passed.
- **Real Chromium with a disposable database:** Esri is the default and actual imagery tiles return 200; no alternate discovery controls; exact search returns all ten audited records; all rendered coordinates match source evidence; automatic zoom contains the full result extent; individual selection/deselection and two-feature preview work. Two real compartments were committed only to the disposable database. Their native geometry SHA256 matches the original SHP audit, normalized geometry matches the source response, and main-map boundaries preserve exact coordinates. Both sectors persisted after refresh, backend restart and a fresh authenticated context. Repeating registration was identified as duplicate.
- **Actual public Chromium:** the same default Esri, exact-only controls, ten exact matches, source coordinate equality, automatic zoom, selection/deselection/multiselect and two-feature registration preview passed. No production registrations were confirmed. No blocking JavaScript exceptions occurred. No territory, bbox or Sentinel requests were made by the workflow.

Production sector count remains **18**, database integrity is **ok**, and every production table matched the fresh activation backup in the final check. Original VMD data was not modified.

## Deployment and evidence

Frontend: `/root/forest_ai/index.html`, `/root/forest_ai/assets/vmd-production.js`, `/root/forest_ai/assets/lvm-geodata.js`; existing `/root/forest_ai/assets/vmd-workflow.css` is unchanged by this scope clarification.

Backend: `forest-api.service`, working directory `/root/forest_ai`, port **8000**. Only this service was restarted at **2026-11-06 13:29:09 UTC**, PID **2708409** at activation. Existing HTML cache prevention, content-hashed scripts and visible release identity remain in use. Other client roots/accounts/services were not deployed over or changed.

Changed application files: `index.html`, `assets/vmd-production.js`, `assets/lvm-geodata.js`, `services/geodata/vmd_production.py`, `services/geodata/vmd_dataset.py`. Tests updated: `tests/test_vmd_production.py`, `tests/test_vmd_production_ui.js`, `tests/test_vmd_test_geojson.js`. New acceptance runner: `scripts/verify_vmd_cadastral_registration.py`; older browser-check entry points delegate to this current workflow.

Backups: `data/backups/cadastral_only_20261106T131934Z/` and `data/backups/cadastral_only_activation_20261106T132845Z/forest_ai.db`; integrity checks passed. No database migration or ingestion was required.

Evidence:

- `data/vmd/cadastral-registration-live-20261106.json`
- `data/vmd/cadastral-registration-persistence-20261106.json`
- `data/vmd/cadastral-registration-live-20261106.png`
- `data/vmd/cadastral-registration-preview-20261106.png`
- `/tmp/cad-only-python.log`, `/tmp/cad-only-ui.log`

Reproduce disposable registration/persistence checks:

```bash
FOREST_PLAYWRIGHT_PATH=/tmp/forest_browser PLAYWRIGHT_BROWSERS_PATH=/tmp/forest_chromium python3 scripts/verify_vmd_cadastral_registration.py
```

Append `--live` for public discovery/preview verification without committing sectors.

## Remaining existing limits

Coverage remains the verified Centra dataset (513,776 records). Existing sector/GPS storage still requires a simple polygon ring; multipart/holed source geometries remain viewable but explicitly non-importable. One registration transaction accepts at most 100 selected compartments. These constraints are not bypassed through approximate geometry.

Live LVM WMS/WFS availability no longer blocks or participates in this cadastral registration page. Esri imagery remains a basemap, not a Sentinel observation pipeline. Sentinel-1/2 archives and automated change detection remain a future phase.
