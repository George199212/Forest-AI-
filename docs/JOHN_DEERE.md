# John Deere Phase 1: Operations Center sandbox

Forest AI is FastAPI (api.py), raw sqlite3 (database.py), shared HTTP Basic auth,
and a vanilla JavaScript SPA (index.html). No Flask, ORM, browser sessions, or
user OAuth existed. Configuration uses environment variables; config.py is unused.
Deployment uses separate API/bot processes and client copies (deploy/ and
CLIENT_INSTANCES.md). No deployed process or service is restarted by this change.
The satellite integration uses client credentials and is not a suitable user OAuth pattern.

This integration adds a dedicated client and router under services/integrations/,
reuses its Fernet helper, and uses the existing Integrations page. It does not use
the generic demo/telemetry sync pipeline or claim TimberMatic support. That
separate catalog entry remains planned. ISO/AEMP has only a separate placeholder.

## Official documentation verified 2026-10-28

- https://developer.deere.com/precision/get-started — sandbox catalog, Organizations,
  pagination, Connections, and manage_connection; sandbox data is real customer
  data, not generated machine samples.
- https://developer.deere.com/dev-docs/machine-locations — Security section documents
  the authorization/token URLs, callback, client credentials in POST body,
  refresh flow, eq1 read permission and offline_access for refresh tokens.
- Authorization: https://signin.johndeere.com/oauth2/aus78tnlaysMraFhC1t7/v1/authorize
- Token: https://signin.johndeere.com/oauth2/aus78tnlaysMraFhC1t7/v1/token
- Catalog: https://sandboxapi.deere.com/platform/

OAuth uses Deere's shared sign-in server; all resource calls are sandbox-only.
Scopes: `eq1 offline_access`: equipment read from the approved API family and
refresh tokens. No write, field, finance, staff/partner-management, or telemetry
measurement permission is requested. No production resource endpoint is implemented.
Organizations and nextPage URLs are discovered. Connections URLs are read from
responses, validated, and followed intact. After saving, return manually to Forest
AI and Refresh; no undocumented return parameter is appended. manage_connection
is an optional user action, never an automatic redirect.

## Setup and run locally

Use a local checkout with a local DB; starting the API also starts the existing
risk worker. Do not start a second API against the running deployment database.
If this directory is on a VPS, copy the checkout to your workstation first:
`localhost` in Deere's registered callback refers to your browser's computer.

Set these in the local `.env` (already gitignored):

```dotenv
JOHN_DEERE_CLIENT_ID=<your existing application ID>
JOHN_DEERE_CLIENT_SECRET=<your existing secret>
JOHN_DEERE_REDIRECT_URI=http://localhost:9090/callback
JOHN_DEERE_ENV=sandbox
INTEGRATION_CREDENTIALS_KEY=<stable encryption key>
DASHBOARD_USERNAME=<dashboard login>
DASHBOARD_PASSWORD=<dashboard password>
```

Reuse your current encryption key if one exists. To generate a new key for a new
local instance only: `python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`.
Store it privately; losing/changing it makes existing credentials unreadable.

Start (the existing application does not load .env automatically; this assumes a
trusted shell-compatible .env):

```bash
cd /root/forest_ai
set -a
. ./.env
set +a
python3 -m uvicorn api:app --host 127.0.0.1 --port 9090 --workers 1 --no-access-log
```

Dependencies: existing requirements.txt, plus the project's existing runtime
needs python-multipart and httpx if absent (listed there after this change).
Open **http://localhost:9090/#integrations**, sign in with Dashboard Basic auth.
Always use localhost, not 127.0.0.1, to preserve callback session cookies.

1. Click Connect John Deere.
2. Sign into Deere; click Allow Access.
3. Deere returns to /callback; Forest AI exchanges tokens and discovers organizations.
4. If shown, click Authorize Organization.
5. Select your Operations Center organization(s) in Deere Connections and Save.
6. Return to http://localhost:9090/#integrations and click Refresh.
7. Inspect organization names and per-organization connection status; use Manage
   connection if returned. Unknown means the response did not establish access.

With no organizations, zero is displayed. No machine API is called, no sample
machine data is generated, and absence of machine data cannot fail Phase 1.
Live acceptance requires actual configured credentials, a Deere login, and an
organization. Automated tests mock all Deere network calls; passing them is not
proof that a live Deere organization is connected.

## Persistence and security

Startup's existing additive migration creates two new tables (no ALTER/DROP or
operational data writes):

- john_deere_oauth: provider, authenticated Basic account ID, Fernet-encrypted
  access/refresh token JSON, expiry epoch, connected/updated epochs, status, and
  sanitized diagnostics/organization metadata. Refresh rotation preserves the
  original connected time and retains an old refresh token if omitted by Deere.
- john_deere_sessions: hashed random HttpOnly SameSite=Lax browser session cookie,
  Basic account ID, CSRF token, one-use OAuth state (10 minutes), session expiry
  (one hour). State is consumed atomically; expired sessions are cleaned up.

All routes remain behind existing Basic authentication, including callback.
Connect and Refresh require CSRF tokens. Only browser CSRF values reach JS;
OAuth credentials and raw API payloads never do. Cookies use Secure on HTTPS;
HTTP is allowed for loopback callback testing only. A single-worker lock protects
shared-account token refresh rotation (matches the existing deployment model).
Use one worker; multi-process refresh coordination is out of scope.

Callback middleware removes its query from ASGI access logs even for authentication
failures, sets no-store/no-referrer, and responses never echo Deere errors, codes,
or tokens. The documented start command disables access logging as defense in depth.
Any external reverse proxy must also omit /callback query strings from its logs.
HTTP timeouts are 5s connect/25s read, redirects disabled, discovered resource URLs
restricted to sandboxapi.deere.com, browser actions to connections.deere.com.
Failures expose fixed messages and HTTP codes, not upstream bodies or exceptions.

Backup before implementation:
`/root/forest_ai_backups/john_deere_phase1_20261028T070024Z/`
(source.tar.gz and SQLite online backup). No live database migration was run during
implementation. New tables are created on the next normal application startup.
To revert code, restore the changed source files from the archive and remove new
Deere files; unused new tables can remain. Do not overwrite an active database
with the backup, as that would discard subsequent operational changes.

## Checks

```bash
python3 -m pytest tests -q
python3 -m compileall -q api.py database.py services tests
```

In this restricted execution environment, standard TestClient runs stalled at
AnyIO's cross-thread event-loop wakeup (including the unchanged existing tests).
Validation used `/tmp/forest_ai_run_tests.py`, a temporary runner that bounds
selector polling to 10ms. It calls pytest without changing application logic or
tests. Outside this sandbox, use the normal pytest command above. Existing UTC
and FastAPI lifespan deprecation warnings remain outside this change's scope.
