# client/ingka: TEMPORARY, private, never merge

This branch holds the client-specific changes of the Ingka Investments Latvia instance
(`/root/forest_ai_ingka`, port 8004). They must stay out of core until the tenant
architecture decision is made. The generic routing mechanism lives on
`feature/telegram-tenants` (`docs/TELEGRAM_TENANTS.md`).

- **Base:** `574bd97`, the commit the instance was deployed from (`data/DEPLOYED_COMMIT`).
- **Snapshot taken:** 2026-11-09, read-only, from `/root/forest_ai_ingka`.

| file | change against 574bd97 | state in this branch |
|---|---|---|
| `api.py` | +15: `GET /api/telegram/positions`, the registered workers of tenant `ingka-investments-latvia`, sector `ING-001`, with their latest position and session track | byte-identical to the instance |
| `index.html` | +19/−2: Ingka title and logo text; map layer drawing worker positions and tracks from `/api/telegram/positions` | byte-identical to the instance |
| `assets/i18n-lv.js` | 1 comment line | byte-identical to the instance |
| `telegram_worker.py` | new file: an earlier Ingka-only worker. **No systemd unit or process uses it**; the live worker is the generic `worker.py` | **redacted in 2 lines** (see below) |

The redactions in `telegram_worker.py` follow the repository rule: no tenant DB paths or
invite codes in git.
- The hard-coded Ingka DB path is replaced by `os.environ['DB_PATH']`. The instance file
  instead asserts that `DB_PATH` equals the hard-coded path.
- The hard-coded invite code is replaced by `FOREST_TENANT_INVITE_INGKA`.

Not included: `telegram_handlers.py`. It is generic, identical in the Rīgas meži and Ingka
instances, and covered under "Not covered yet" in `docs/TELEGRAM_TENANTS.md`.

Delete this branch once the decision is made: either fold generic parts into core
(configurable branding, a tenant-aware positions endpoint), or move the client code to its
own repository.
