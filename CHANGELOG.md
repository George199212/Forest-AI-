# Changelog — Forest AI

Newest first. Entries describe branches; "deployed" is stated explicitly when a release is active.

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
