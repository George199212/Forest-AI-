# Sector cleanup = ARCHIVE — preview (owner D14, 2026-11-18)

**Preview only. Nothing has been written to any database.** Source: `.backup` copies taken 2026-11-18T06:22:42Z
(`/root/sectors_sandbox/data_20261118`, forest_ai.db sha256 `b05a6b79429b5843…`, satellite.db
`b727162e5955c031…`), inventory by `scripts/sector_inventory.py` (read-only, refuses live paths).
One sector name contains a personal surname and is shown redacted, as in the Stage 0 fixtures.

## 1. What would change (after approval, in this order)

1. **Blocked first by §0a:** no archive write to production before the owner confirms the OLD-server reconciliation is closed.
2. Immediately before applying: `sqlite3 forest_ai.db ".backup '<dst>'"` and the same for satellite.db, sha256 of both recorded
   (the copies used for this preview are evidence of the state *now*, not the backup for the apply step).
3. Schema (additive, needs approval as a schema change):
   ```sql
   ALTER TABLE sectors ADD COLUMN archived_at TEXT;      -- UTC ISO, NULL = visible
   ALTER TABLE sectors ADD COLUMN archived_reason TEXT;
   ```
4. One transaction: `UPDATE sectors SET archived_at=:now, archived_reason='owner D14 2026-11-18: keep only BIK-001 visible'
   WHERE id IN (<84 ids below>) AND archived_at IS NULL;` — no DELETE, no other table touched.
5. Satellite: `POST /api/sat-monitoring/areas/4/stop` (sector 76) → STOP_AREA job → `active=0`, history kept.
   BIK-001's area 1 stays active. Areas 2 (Ķekava EVAL_BBOX) and 3 (LVM_GEO, belongs to no sector) are not sectors:
   **not touched by D14** — say if they should be stopped too.
6. First on a DB COPY + sandbox; production in a separate approved step (never bundled with the UI release).

## 2. Read paths that must hide archived sectors (`WHERE archived_at IS NULL`) — code change, Stage 2

| Path | File:line | Change | Note |
|---|---|---|---|
| Sectors list (legacy) | api.py:722 `GET /api/sectors` | filter | |
| Sectors cards (new, D6) | `GET /api/sectors/cards` | filter; `?include_archived=1` for audit | |
| Objekti | api.py:818 (`/api/objects` grouping), :2360 | filter | |
| Overview counts / selects | api.py:297, 683, 690, 1548, 2025, 2624 | filter (each reviewed: counts vs dropdowns) | |
| Telegram bot sector list | bot.py:581 | filter | **forest-bot restart** needed at release; tenant workers have their own DBs (not touched) |
| Satellite "Pievienot sektoru" | satellite_monitoring/store.py:572 `sectors()` | filter | Stage 5 file — after its release |
| **Meža karte polygons** | **services/geodata/forest_map.py:222** | filter | **Codex / LVM GEO file — this task must not touch it.** Needs the owner to assign it (Codex or an exception) |
| **GPS classification** | **services/geodata/gps_map.py:71** | **decision**: should a GPS point inside an archived sector still count as "inside registered sector"? | same Codex-owned folder |
| Still resolvable by id | `/api/sectors/{name}`, `#sectors/{id}`, risks/incidents/photo-compare/evidence links | **no filter** | page shows an "Arhivēts" chip |

## 3. Findings the owner should see before approving

- **Demo scenarios:** `services/demo_scenarios.py:166 _find_sector` uses **A-005, A-006, A-007** by name. It keeps working
  (no archive filter there), but the demo would create risks/incidents for sectors that are hidden everywhere → the demo
  becomes invisible. Keep these three visible, or accept that the demo is retired.
- **Real operational history** on A-004 (49 rows), A-005 (34), S-004 ×2 (17, name shared by ids 9 and 18), A-006 (7):
  archiving hides the sectors, the rows stay; Risks/GPS lists still show them by name.
- **Sector 76** is the only monitored sector besides BIK-001 (area 4: 158 acquisitions) → stop, data kept.
- **Orphan names** (rows whose `sector` matches no sector, unaffected by D14): risks 'A-005 — <client>' ×5, 'A-007' ×2,
  'Kekava positive control' ×1, 'TEST-STAGE1B' ×1, 'TEST-STAGE2B' ×1; sector_employees 'A-007' ×1; ai_inspector_analyses NULL ×15.
- `geodata_sources` has an FK to sectors with **ON DELETE CASCADE** — another reason the archive never deletes.
- **Interplay with D13:** after this archive, the auto-monitoring reconciler has **no candidates** (BIK-001 is monitored);
  it would only enrol future registrations.
- <client> :8002 / <client> :8004 / Review :8003 have their own DBs: not part of this preview.

## 4. Counts (the per-sector table is kept OUT of git)

The full per-sector list (ids, names, per-table reference counts, proposed action) is at
**`/root/sectors_sandbox/D14_preview.md`** on the server (not tracked, mode 0600), owner decision 2026-11-18.

| Group | Sectors | Proposed action |
|---|---:|---|
| BIK-001 (id 26) | 1 | **keep visible** (area 1 stays active) |
| LVM GEO / VMD registrations (ids 30–97) | 68 | archive; each has only its `geodata_sources` + `geodata_boundary_history` rows; 1 monitored (sector 76 → stop area 4) |
| Legacy / demo / test (ids 1–21) | 16 | archive; 9 of them have operational rows by name (sessions, photos, risks, AI analyses, employees, vehicles, snapshots) — rows stay |
| **Total** | **85** | **84 archive, 1 keep** |

Archive rule: `archived_at IS NULL` = visible; archived sectors are hidden from lists (Sectors, Objekti, Meža karte, bot,
satellite "add sector") and stay resolvable by id for audit/evidence links; no row is deleted; satellite areas of archived
sectors are stopped, never deleted.
