# Phase 2B — manual customer machine synchronization (Sandbox)

## Implementation versus verification

The pipeline is IMPLEMENTED and covered by mocked software tests. It is **NOT
VERIFIED WITH REAL DEERE MACHINE DATA**. No customer machine or telemetry records
are bundled, seeded, fabricated, or substituted when API responses are empty.
Only fresh authenticated sandbox responses feed manual synchronization. The UI
keeps the acceptance label conservative; receiving a response does not certify
all telemetry capabilities or operational risk policies.

The existing OAuth source, encrypted token persistence, scope, refresh, redirect,
API catalog, Organizations, Phase 2A diagnostics, Test John Deere API, and ISO
Fleet service are preserved. No process is started/restarted by implementation.

## Existing Forest AI relationships

- Objects group forestry sectors by `boundary_plan_id` (boundary-plan/parcel).
- Machines/equipment already live in `sector_equipment`; `sector` references a
  sector name. This is reused for Deere and future providers, not duplicated.
- `vehicle_gps_pings` already carries equipment history via `entity_type=EQUIPMENT`
  and `equipment_id`; it is reused for provider position history.
- `risks` links an equipment incident through `entity_type=EQUIPMENT`, `entity_id`;
  `risk_events` is its audit history. Real Deere alert risks use these tables.
- Restricted wetlands/zones found in demo_scenarios are simulated scenario geometry,
  not customer configuration. They are never evaluated against Deere machines.

New imported machines use `sector=''` because the existing column is NOT NULL.
This means **Unassigned**, not an invented sector or geographic relationship.
No synthetic parcels/sectors are created. Objects shows all imported machines
and lets the operator assign a real existing sector; parcel cards count machines
assigned through their sectors. Blank assignment remains valid. Sector names
must identify one real sector; ambiguous or simulated/demo assignments are rejected.

## Manual controls and sequence

Integrations → John Deere now contains:

- Sync Organizations: catalog-first discovery; upsert external organization refs.
- Sync Machines: refresh organizations, follow returned org/self/equipment/machines
  links, then upsert existing `sector_equipment` by `(provider, external_machine_id)`.
- Sync Telemetry: refresh discovery and read each available machine capability.
- Sync All: organizations, machine metadata, and independent telemetry reads.

Discovery needs explicit Machine classification or a machine relation; implements
are not presented as motorized machines. Machine-detail links can expose further
capabilities. No resource URLs/IDs are constructed or guessed.

There is no background polling/scheduler. Manual actions share a 60-second default
cooldown. Prefer Sync All; otherwise wait for that cooldown between actions.
A Deere 429 persists its Retry-After delay and stops requests. A configurable
request budget bounds each run. No retry storm is started.

A successful empty result is EMPTY/WAITING, not an error. Missing equipment is not
deleted; missing metadata does not erase known metadata. Organization references
not present in a subsequent successful response become NOT SEEN, not deleted.
They are not counted as currently connected. A failed organization response does
not change previously seen references. Stored machine counts include retained
machines even when the latest customer discovery is empty.

The panel shows counts, last completed syncs, safe sync history, stage errors,
and Customer Readiness. READY denotes an implemented/authenticated layer;
CONNECTED/RECEIVING describe stored customer data. They do not certify end-to-end
live acceptance. The current Phase 1 state with zero organizations remains normal.

## Telemetry and monitoring

Per machine, capabilities are attempted independently through returned links:
latest location, location history, breadcrumbs, engine hours, hours of operation,
alerts, and device state reports. Missing links are unavailable, not fabricated.
403/404 or provider/network failures for one capability do not prevent other
capabilities/machines. AUTH REQUIRED and RATE LIMITED stop the run safely.

Fresh machine discovery precedes telemetry to avoid using saved links after access
changes. Saved links remain server-side only. The inherited secure refresh logic
runs before a request when necessary and retries one resource 401 after refresh.
Refreshed credentials remain encrypted through the existing token store.

GPS supports Deere `point` plus eventTimestamp/createTimestamp as documented at
https://developer.deere.com/dev-docs/machine-locations. Latitude/longitude zero are
valid; invalid coordinates never become 0,0. A location with no timestamp may be
shown with "Not available" for time, but no receipt timestamp is substituted as
a provider report. Timestamped GPS goes into the existing GPS history with its
original source timestamp, provider/source=john_deere, and equipment ID. A
provider/position/time fingerprint prevents duplicate history points. Older
points can extend history without replacing the latest position. Future-invalid
readings do not establish fresh telemetry health.

Engine/device/operating readings use per-field source timestamps to prevent older
responses overwriting newer readings. Hours-of-operation events remain events;
engine-on intervals are not invented cumulative hours. Cumulative operating hours
are populated only when a numeric cumulative reading is actually returned.
Optional telemetry summaries reuse `integration_records`, with links, Wi-Fi SSIDs,
and unrelated device payload fields excluded.

Map uses the existing Leaflet map and an additional machine marker layer. Clicking
shows actual available metadata, organization, GPS/time, engine/operating hours,
device status, health, geofence, and last sync. Missing fields show Not available.
Positions without a sector are visible without implying geofence authorization.
Provider/alert text is escaped for HTML rendering. Existing sector map API shape
and parcel Objects API shape are unchanged; `/api/map/machines` provides equipment
for Objects/Map and supports future provider identifiers.

Sector geofence reuses `services.geo.point_in_polygon` and existing WGS84
`[lat,lon]` sector polygons. Result is INSIDE/OUTSIDE/UNKNOWN. No boundary, missing
relationship, malformed polygon, or ambiguous name yields UNKNOWN, never a risk.
Restricted zones stay UNKNOWN because no real configured zone registry exists.
No demo wetland, guessed water, bog, or protected-area boundaries are imported.

Telemetry health is informational, recalculated from real source timestamps:

```dotenv
JOHN_DEERE_SYNC_MIN_INTERVAL_SECONDS=60
JOHN_DEERE_SYNC_MAX_REQUESTS=100
JOHN_DEERE_TELEMETRY_STALE_SECONDS=21600
JOHN_DEERE_TELEMETRY_OFFLINE_SECONDS=86400
```

Defaults are LIVE below six hours, STALE at six hours, OFFLINE at 24 hours;
missing/invalid timestamps are UNKNOWN. Deere call-in cadence varies: review these
conservative UI defaults with the customer's actual reporting policy. Thresholds
are configurable and do not create offline/movement risks. No telemetry health
polling process is started.

## Real alert → equipment risk

Deere alert field/severity reference:
https://developer.deere.com/dev-docs/machine-alerts.
Real alerts are stored in `integration_provider_events`, keyed by provider,
equipment ID, and returned external alert ID. With no ID, a stable fingerprint
requires an actual timestamp+description. No identifier is fabricated in the
external_event_id field. Repeat alerts update the same event/risk.

Non-ignored, visible, unacknowledged HIGH/MEDIUM/LOW alerts (or documented
RED/YELLOW color severity) create an EQUIPMENT_BREAKDOWN incident linked to
the existing equipment ID. INFO alerts are stored as information, not promoted
into failures. Existing closed risks stay closed on replay. Provider events,
incidents and audit references are persisted in one SQLite transaction to prevent
crash-created orphan/duplicate risks. Acknowledgement updates provider event state;
it does not silently resolve a Forest AI incident. Events absent from one response
are not automatically resolved. Alert risks can exist before sector assignment;
assigning a sector updates open equipment risk relationships. No Telegram message
or inline AI call is initiated by this service (existing worker behavior remains).

Automatic geofence/offline/restricted-zone/movement risks remain disabled pending
real telemetry and approved customer policies. Existing future risk mappings remain.

## Database migration

Existing additive migration helpers add nullable fields to `sector_equipment`:
telemetry_timestamp, telemetry_health, geofence_status, restricted_zone_status,
device_status, provider_links_json, engine_hours_timestamp,
operating_hours_timestamp, device_status_timestamp.

A global partial unique index on `(provider, external_machine_id)` enforces the
requested stable identity. Phase 2A's scoped identity index remains compatible.
If someone manually bound the same Deere ID to multiple old rows before Phase 2B,
the unique-index migration stops for review; no rows are merged/deleted silently.

`vehicle_gps_pings` gains provider, source, source_timestamp, provider_record_key
and a dedup index. Existing GPS writers and routes remain compatible.

`integration_sync_runs` is reused, adding provider, sync_type, completed_at,
organizations_processed, machines_processed, telemetry_records_processed,
errors_count, result_json. Existing adapter run fields remain intact. Telemetry
counts represent inserted GPS/staging records, not a unique machine count.

Two generic reference tables are added:

- integration_organizations: provider+external org ID, name, authenticated account,
  connection status, last sync. Does not replace internal Forest AI tenant orgs.
- integration_provider_events: external event refs, equipment ID, risk ID, timestamp,
  severity, description, active state, last sync. Does not replace Risks.

Existing `integrations` metadata provides a single Deere provider row on first
manual synchronization; no demo adapter/catalog replacement is introduced.
No machinery or GPS history tables are duplicated. No rows are dropped/seeded.
Migrations were exercised on temporary test DBs, not the live operational DB.

## Error/status contract and security

401 after refresh / failed refresh → AUTH REQUIRED; 403 → PERMISSION REQUIRED;
404 → RESOURCE UNAVAILABLE; 429 → RATE LIMITED; 5xx → PROVIDER ERROR;
network failure/timeout → TEMPORARY ERROR. Mixed recoverable machine failures
produce PARTIAL with per-capability safe status codes. Request budgets/cooldowns
prevent aggressive polling. Secrets, Authorization headers, codes, and upstream
response bodies never enter sync history, diagnostic output, or frontend data.

All new routes inherit HTTP Basic authentication. Sync/sector changes require the
existing browser CSRF session and reject cross-origin requests. Sector mapping
checks real equipment ownership and existing real sectors. Shared Basic auth is
still a single-tenant boundary, not a new multi-user authorization model.
OAuth exchange/refresh code and client credentials have not been changed.

## First real customer: exact manual procedure

1. In a maintenance window stop only the manually running 9090 test process with
   Ctrl+C. Do not start a duplicate or restart production services.
2. Start the current test application (the existing startup migrates additively):
   `cd /root/forest_ai && (set -a && . ./.env && set +a && exec python3 -m uvicorn api:app --host 127.0.0.1 --port 9090 --workers 1 --no-access-log)`.
3. Open http://localhost:9090/#integrations via the same localhost/SSH forwarding
   setup that already worked for Phase 1. Customer signs into Forest AI.
4. Connect John Deere → Deere login → Allow Access → callback. Reuse working
   OAuth if the correct customer account is already connected.
5. Authorize Organization → select real Operations Center organization(s) → Save.
   Return to Forest AI → Refresh → Test John Deere API. Confirm connected count.
6. Sync Organizations. Confirm returned real Deere organization IDs/names/counts.
7. Wait 60 seconds → Sync Machines. Confirm real machines appear once in Objects.
   Repeat after cooldown to confirm IDs and counts remain stable.
8. In Objects, assign each relevant machine to its actual existing Forest AI sector;
   leave unknown assignments Unassigned. Do not invent geographic relationships.
9. Wait for cooldown → Sync Telemetry (or Sync All). Inspect safe stage statuses,
   counts and last sync times. Permission-required capabilities remain unverified.
10. Open Objects and Map. Compare Deere GPS, original timestamp, engine hours,
    device state and reporting cadence against the customer's Operations Center.
11. If an actual actionable machine alert exists, inspect Risks and its equipment
    association. Repeat synchronization and confirm the same external alert does
    not create another incident. Do not fabricate an alert for UI acceptance.
12. Confirm missing telemetry displays Not available/UNKNOWN and that no geofence
    risk appears for unassigned machines. Review health thresholds with customer.
13. Record accepted capabilities separately. Do not treat readiness labels or
    mocked tests as live telemetry certification.

Until a real connected organization supplies accessible machines, live equipment
schemas/IDs, resource links, GPS and timestamps, hours, alerts, device states,
Map markers, customer assignment, geofence accuracy and end-to-end real risk
deduplication cannot be accepted. With zero data, only OAuth/catalog/empty-data
handling and safe manual synchronization are live-verifiable. Restricted-zone and
movement/offline risk policies require real configuration and separate approval.

## Verification and rollback

Automated tests use isolated temporary SQLite databases and test-only HTTP mocks.
Run `python3 -m pytest tests -q`, Python compileall, JavaScript syntax checks, and
`git diff --check`. In the restricted tool environment use the temporary selector
polling test runner documented in Phase 1; application logic is unchanged by it.
There was no live network or browser acceptance test in this environment.

Pre-change source and online SQLite backup:
`/root/forest_ai_backups/john_deere_phase2b_20261028T075006Z/`.
Rollback code from source.tar.gz if necessary; nullable schema additions can remain.
Never replace a running operational database with an older snapshot, as later
Forest AI records would be lost.
