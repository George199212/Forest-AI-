# Changelog — Forest AI

Newest first. Entries describe branches; "deployed" is stated explicitly when a release is active.

## 2026-11-13 — DEMO release `forest-review-geo-20261113T1023Z` (prepared, NOT active on :8003)

Branches (none merged to master): `feature/review-integration-layer` (`b781eaa`, the demo's review layer as
deployed since 2026-10-21, now in git), `feature/live-vmd-ui-texts` (`50f6daf`, the two live-only :8000 VMD UI
files), `feature/review-geo-release` (66572fa + both + the demo changes below).

### Demo (ACCESS_MODE=review only; production behaviour unchanged, tested)
- LVM GEO + Meža karte in the demo sidebar (Admin group). The standalone Map item is kept for the demo.
- Server-side blocks with a bilingual 403 (`registration_disabled_in_demo`, `incident_creation_disabled_in_demo`)
  for `/api/geodata/vmd/import-selected|import|territories`, `/api/geodata/lvm/preview|import|apply|sectors/*`
  and `/api/geodata/forest-map/gps/violations/incident`, plus handler-level guards.
- `REVIEW_MAP_EXCLUDED_SECTORS`: display-only exclusion of listed sectors on the geodata read connections.
- Seeded worker sessions inherit the sector's `data_origin` (SIMULATED) on Forest Map instead of REAL.
- UI: visible disabled register / incident buttons with an LV/EN note. English overlay for LVM GEO and
  Forest Map, with official Latvian registry terms in parentheses and source values never rewritten.
  Forest Map defaults to EN only when the EN overlay is loaded.
- Fix found during verification: a review-UI MutationObserver write loop that froze AI Inspector (`f3165b4`).

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
