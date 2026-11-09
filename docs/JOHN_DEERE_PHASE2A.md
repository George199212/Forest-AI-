# John Deere Sandbox Phase 2A: diagnostics and machine readiness

## Scope and usage

Phase 1's OAuth module (`services/integrations/john_deere.py`), scopes, callback,
client credentials, encryption key, token exchange, and token refresh are unchanged.
The separate diagnostics service uses the existing authenticated client and stored
token. No credentials or configuration changes are needed.

Restart the manually running 9090 process to load code and additive schema changes:
stop that process with Ctrl+C, then use the same command from Phase 1:

```bash
cd /root/forest_ai && (set -a && . ./.env && set +a && exec python3 -m uvicorn api:app --host 127.0.0.1 --port 9090 --workers 1 --no-access-log)
```

Do not launch a second process against port 9090. Open
http://localhost:9090/#integrations and click **Test John Deere API**. No reconnect
is needed for a valid token. The protected POST `/api/john-deere/test` requires
the existing browser CSRF token; no secrets reach JavaScript. Opening the page
reads saved diagnostics only and does not make Deere network calls.

Diagnostic order: catalog → organizations → connected organization self links →
returned equipment/machines collection links → separate ISO Fleet diagnostic.
Calls use the stored OAuth token and existing refresh support. Machine-specific
telemetry is not requested by this sequence. Resource methods are prepared for
explicit future reads against a real machine identity and Deere-provided links.

Double clicks/retests within 60 seconds reuse diagnostics. Successful Fleet
results are cached for one hour following Deere's polling guidance. Stage errors
show separately; no automatic rate-limit retry loop is added. An API error is not
silently converted into an empty resource collection. Counts may be incomplete
when an equipment request fails and are explicitly labeled accordingly.

## Empty data and connection status

A successful zero-organization response displays:

> No John Deere organizations are available for this account.
> OAuth and API connectivity are working correctly.
> Connect a John Deere Operations Center organization with machine data to test telemetry.

Equipment count is 0 with `Waiting for organization data`. API CONNECTION remains
WORKING when catalog and organization requests succeed. ORGANIZATION DATA is
WAITING and MACHINE DATA is WAITING FOR REAL JOHN DEERE ORGANIZATION. A connected
organization with an empty equipment collection is also success. A missing
equipment link is distinguished from a successful empty equipment response.

Equipment includes implements; Machines counts explicit Machine classifications,
objects returned from a machines link, or equipment with a machine relation.
Counts deduplicate by organization and external identifier. Fleet count is shown
separately; it is not merged with Operations Center machines and could overlap.

Fleet statuses: `available` for successful XML containing Equipment elements,
`empty` for a valid empty Fleet or HTTP 204, `error` for transport/XML/HTTP failures,
`not tested` before execution. 401 can trigger the existing token refresh and one
retry. 403, 404, 429, and 500 are errors, not evidence of zero machines. Fleet
connection actions are validated, stored server-side, and exposed through the
existing Authorize Organization/Manage connection routes without leaking URLs or
credentials into API diagnostic payloads.

## Official Deere references (verified 2026-10-28)

- https://developer.deere.com/precision/get-started documents catalog-first
  discovery and `https://sandboxaemp.deere.com/Fleet/{pageNumber}`.
- https://developer.deere.com/dev-docs/aemp documents XML, eq1/offline_access,
  Fleet pagination through `next`, and an hourly server cache.
- The AEMP endpoint reference currently renders a conflicting duplicated
  `/Fleet/Fleet/{pageNumber}` path, while the getting-started guide explicitly
  gives `/Fleet/{pageNumber}`. This implementation uses the latter, starting
  `https://sandboxaemp.deere.com/Fleet/1`. If Deere returns 404 it is reported as an
  endpoint error; no guessed fallback or false EMPTY classification occurs.
- https://developer.deere.com/dev-docs/machine-locations
- https://developer.deere.com/dev-docs/machine-engine-hours
- https://developer.deere.com/dev-docs/machine-hours-of-operation
- https://developer.deere.com/dev-docs/machine-alerts
- https://developer.deere.com/dev-docs/machine-device-state-reports

Operations Center requests follow returned sandboxapi.deere.com links only. A
link to another host is rejected rather than sending a bearer token there. ISO
uses an independent XML transport restricted to sandboxaemp.deere.com/Fleet/;
production hosts, redirects, unsafe XML declarations, oversized XML, cycles, and
excessive pagination are rejected. No scopes or licenses are added.

## Existing equipment model and migration

The existing `sector_equipment` table remains the machine system. Objects in this
application group sectors; machines already belong to a sector. No parallel
John Deere machine table or synthetic sector is introduced.

Startup adds nullable columns using the existing `_add_column_if_missing` helper:
provider, external_account_id, external_organization_id, external_machine_id,
machine_name, serial_number, latitude, longitude, location_timestamp, engine_hours,
operating_hours, machine_status, last_alert, last_synchronization_time.
Existing `type`, `brand` (make), and `model` fields are reused. A partial unique
index prevents the same Deere identity being assigned to multiple equipment rows.
No existing data or defaults are overwritten. Migration tests verify idempotency.
The migration has only been applied to temporary test databases in this session.

`MachineService` prepares latest location, history, breadcrumbs, engine hours,
hours of operation, alerts, and device state reports. Each requires an external
ID and a returned API relation. Missing relations are unavailable; missing GPS or
measurements remain NULL. `snapshot()` can normalize optional linked telemetry
without persistence. Hours-of-operation events are retained as events rather
than misrepresented as cumulative operating hours. Optional API errors propagate
instead of fabricating measurements.

`bind_existing()` is a future explicit binding/metadata synchronization entry
point to an existing real, sector-assigned equipment row. It rejects demo rows,
identity conflicts, and duplicate bindings. Missing fields preserve existing
values. It is intentionally not exposed as a route or called by diagnostics.
A future reviewed sync action/scheduler must choose an existing equipment row,
obtain fresh real machine data, and apply telemetry snapshots. Phase 2A does not
automatically poll, create machines, assign sectors, or overwrite operational
status used by existing workflows.

`RISK_MAPPING` declares future equipment alert, reporting-loss, sector-exit,
restricted-zone, and movement-anomaly rules with required real-data prerequisites.
No evaluator, AI request, alert send, incident creation, or timer is enabled.
Offline/zone/movement rules require configured policies/boundaries before use;
missing telemetry alone is not a risk.

## Verification and remaining live work

The saved live Phase 1 snapshot read during development showed OAuth OK, token
Valid, API Catalog OK, Organizations 0. This is saved evidence, not a new Deere
API call. New live diagnostics could not be executed because this agent's
execution environment prohibits network sockets. The application was not
restarted and no current service was interrupted.

Automated tests mock Deere only inside pytest fixtures. There is no runtime
fixture provider or fallback to test telemetry. They cover equipment present/
empty, zero organizations, connected/unconnected organizations, optional locations,
alerts/engine readings, machine-link methods, binding safety, Fleet XML/empty/
pagination/connections, token refresh, 401/403/429/500, authentication and CSRF,
secret-free responses, and no operational/risk writes during diagnostics.

Normal verification commands:

```bash
python3 -m pytest tests -q
python3 -m compileall -q api.py database.py services tests
git diff --check
```

This restricted runner requires the temporary selector-polling workaround described
in JOHN_DEERE.md for FastAPI TestClient; this does not change application logic.

Without a customer, the VPS button can verify live auth/catalog/organizations,
zero-data behavior, and the actual Fleet access result. Full end-to-end equipment,
location, hours, alerts/device reports, sync mapping and telemetry-driven risk
validation remain dependent on a connected real organization with suitable data.

Pre-change backup:
`/root/forest_ai_backups/john_deere_phase2a_20261028T073947Z/`
contains Phase 1 source and a SQLite online backup. Do not overwrite a running
operational DB to roll back code; new nullable columns can remain unused.
