# Changelog — Forest AI

Newest first. Entries describe branches; "deployed" is stated explicitly when a release is active.

## 2026-11-16 — `feature/satellite-monitoring`: status from the worker + Forest Map layer "Satelīta izmaiņas" (not deployed)

### Satellite Monitoring status (`/api/sat-monitoring/health`, overview banners)
- Copernicus status now comes from the worker's own records (`sat_provider_status` + latest `sat_runs`), not from
  the API process environment. States: OK (no banner) / DEGRADED (latest call or run failed after the last success;
  sign-in failures marked, with timestamp and error) / NOT_CONFIGURED (only when the worker itself reported missing
  credentials) / UNKNOWN ("Status unknown", never "not configured"). `credentials_configured` removed from `/health`.
- Queue banner names the exact missing schema items (`queue.missing`) and says the API never migrates the DB; new
  READ_ONLY state when the API process cannot write satellite.db. `schema_stage2` now checks everything `rw()` needs.
  "Fetch now" is disabled only for NOT_CONFIGURED or a queue that is not READY.
- Deep links `#sat-monitoring?event=<id>` / `?area=<id>`; late responses no longer overwrite a newer view.
- Satellite Monitoring is excluded from the 30 s dashboard auto-refresh (it threw an open event/area page back to
  the overview).

### Forest Map (Meža karte)
- Optional layer "Satelīta izmaiņas" (off by default): current-generation change masks of monitored areas, styled by
  status (Suspected magenta / Recovered grey dashed / Reviewed blue) + Sentinel observation footprint per area.
  Own pane (z 380, below GPS tracks/markers). Popup: event id, area, onset, changed area, zone, confidence, status,
  "Atvērt notikuma lapu".
- New read-only endpoint `GET /api/sat-monitoring/map-layer?area_id=&event_id=`: server-side simplification
  (stdlib Douglas–Peucker; all areas from 10 m, one area/event from 2 m, stepped per area up to a 150 KB cap;
  total ≤ 600 features / ≤ 400 KB, else 413); 404 for unknown area, unknown or superseded event.
  Sandbox copy: all areas 137,679 B (BIK-001 271 B at 10 m, Ķekava 137,353 B at 10 m); BIK-001 alone 313 B at 2 m.
- Deep links `#forest-map?sat_event=<id>` / `?sat_area=<id>` (enable layer, fit bounds, open popup); buttons
  "Atvērt Meža kartē" on the area and event pages. `forest-map.js` hooks only: layer checkbox, `toggleLayer` branch,
  getters `ready/lang/basemap`, `holdView()` (= the existing GPS-session deep-link flag, so the violations overview
  does not re-fit the map away).

## 2026-11-10 — `feature/forest-map-basemap-contrast` (not deployed)

### Forest Map
- Basemap "Karte" (OSM): VMD compartments, review-required compartments, VZD parcels and the generalized
  overview are drawn in darker colours (e.g. compartments `#1e6b34`, 1.6 px) so they stay visible on OSM's
  green woodland. "Satelīts" is unchanged (pixel-identical screenshots).
- Switching the basemap repaints the already-loaded boundary tiles in place: no new tile requests.
- Legend swatches follow the active basemap. On Karte only: selected compartment `#b8860b`, cadastral
  land-unit outline `#1f6fb2`, GPS transitions/gaps with a white casing.

## 2026-11-10 — `feature/lv-ui-global` (deployed 2026-11-10 09:16 UTC via `release/2026-11-10-lvm-geo-lv-ui`)

- Latvian sidebar labels and lv-LV header time on every page (were LVM GEO only).

## 2026-11-10 — `feature/lvm-geo-finish` (deployed 2026-11-10 09:16 UTC via `release/2026-11-10-lvm-geo-lv-ui`)

### Forest Map
- On-map basemap switch "Satelīts" / "Karte" (top-right Leaflet control), synced with the sidebar
  "Pamatkarte" select; choice remembered in localStorage; satellite tile failure falls back to "Karte"
  with a short notice. Overlays stay above the basemap.

### LVM GEO — sector registration
- Selection changes only through explicit controls: polygon click = popup with "Atlasīt" / "Noņemt no
  atlases"; row click = highlight + show on map; off-page selection removed only via its popup button.
  Toggling no longer rebuilds the table (scroll, focus and form values survive).
- Tri-state master checkbox in the "Atlasīt" header (importable rows of the current page); the
  "Atlasīt visus" button is removed; "Noņemt atlasi" clears all pages; 100-item limit kept.
- Sticky action bar under the results: counter (N · ha), Sektora nosaukums, Vārds, Uzvārds and
  "Reģistrēt sektorus (N)" with the reason shown when disabled. Dry-run preview + confirm unchanged;
  preview shows server-side sector names; registered rows show "Reģistrēts" / "Jau reģistrēts"; result
  message with count, ha and a link to Sektori, never a success message when nothing was registered.
- No backend / API / schema change.
