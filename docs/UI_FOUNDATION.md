# UI foundation (phase 1, CSS only)

Branch `feature/ui-foundation`. Status: sandbox-verified, **not deployed**.

## What changed

| File | Change |
|---|---|
| `assets/forest-ui.css` | New. Concept A "Enterprise Dark" tokens, aliases for the legacy variables (`--bg`, `--text3`, `--card`, `--muted` …), shell, components, page fixes, responsive rules, transitional font-size shims. |
| `index.html` | One line: `<link rel="stylesheet" href="/assets/forest-ui.css">` after the inline `</style>`. |

No JavaScript, translation dictionary, element id, API or backend change. The script tags that
`serve_index()` rewrites (feature flags) are untouched.

## Verification (sandbox, 2026-11-16)

Sandbox: release `forest-api-forest-map-contrast-20261110T0949Z` (live :8000 code) copied twice
(before / after = + this branch's two changes), SQLite backup copies of `forest_ai.db`, test-only
Basic Auth credentials, `127.0.0.1:8020–8023`, private mount namespace with `/root` read-only,
`env -i` (no production `.env`), GPS compartment alerts off.

14 routes × 3 widths (1440, 1024, 390) × 2 languages; axe-core 4.12.1, WCAG 2.0/2.1/2.2 A+AA:

| | before EN | after EN | before LV | after LV |
|---|---|---|---|---|
| axe nodes total | 545 | 38 | 532 | 39 |
| color-contrast | 518 | **0** | 505 | **0** |
| scrollable-region-focusable | 18 | 29 | 18 | 30 |
| label / select-name (Satellite page) | 6 / 3 | 6 / 3 | 6 / 3 | 6 / 3 |
| visible text < 11 px | 551 | **0** | 551 | **0** |
| console errors | 3 | 3 | 3 | 3 |
| horizontal page overflow | 0 | 0 | 0 | 0 |

The three console errors are the same before and after: `503 /api/geodata/forest-map/status` on
Forest Map, because the sandbox has no forest-map raster cache (environment, not code).

At 390 px the old layout clipped the right half of every page (sidebar kept 210 px); the new layout
uses a 60 px icon rail. At 1024 px the Sectors table was clipped by 193 px; it now scrolls inside
its card.

Tests: JS UI tests 63/63 pass (basemap 7, overlap 3, lv_ui_global 5, lvm_wms_map 9,
vmd_local_ui 7, vmd_production_ui 29, vmd_test_geojson 3). `tests/test_deployment_delivery.py`
2 passed on master and on the branch. Full Python suite (earlier run today, before the last CSS
edits): identical on master and branch, 10 failed / 287 passed / 3 skipped / 40 errors; all
pre-existing, mostly `tests/test_nationwide_geodata.py`.

## Known issues, deliberately NOT fixed in this phase (JS / HTML / i18n)

1. **Sidebar highlight is positional.** `navMap` maps section ids to item indexes; detail pages
   (e.g. `#sector-BIK-001`) highlight "Pārskats" instead of "Sektori". Fix: `data-section` on
   nav items.
2. **Mixed languages in EN mode.** With `UI_LANGUAGE=en`, Overview KPI labels and table headers are
   Russian (`Секторы`, `Активные риски`, `Подрядчик`), the sidebar and the status badge are
   Latvian. `i18n-lv.js` matches exact strings, so every text change needs dictionary updates.
3. **Scrollable regions are not keyboard-focusable** (`.content`, table wrappers such as
   `#ov-sectors`, `.vmd-table-scroll`). Needs `tabindex="0"` + `aria-label` in HTML/JS. Count rose
   18 → 29 because wide tables now scroll inside their card instead of being clipped.
4. **Satellite page form controls without labels** (2 × `label`, 1 × `select-name`, critical).
5. **Chart.js axes** keep their canvas fonts and long rotated sector names; needs chart options.
6. **Inline `font-size: 9px/10px`** styles are lifted to 11 px by `!important` shims (section 7
   of `forest-ui.css`); remove the shims once inline styles become classes (phase 3).
7. Data content (some risk texts and sector names) is in Russian; not a UI issue.

## Rollback

Release folder: remove the `<link rel="stylesheet" href="/assets/forest-ui.css">` line from
`index.html` (the CSS file may stay; it is inert without the link). Git: revert the commit.
Production activation follows `docs/DEPLOY_RELEASES.md` (new release folder + drop-in) and only
after explicit approval.
