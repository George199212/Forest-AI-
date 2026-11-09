# Telegram multi-tenant routing

One Telegram bot token serves the main Forest AI bot and several client tenants (for
example the Rīgas meži instance and a prospective client). This document describes the
generic, versioned routing code (`telegram_tenant_router.py`, `telegram_tenants/`), its
configuration, its data, a cutover plan from the current unversioned files, and the risks.

State on 2026-11-09: **nothing here is deployed.** Production still runs the unversioned
copies described under "Current production layout".

## How routing works

```
Telegram ──getUpdates──► forest-bot (bot.py, sole poller)
                           │ group -100: telegram_tenant_router.route()   [only if FOREST_TENANT_ROUTING=1]
                           │   admin?      → admin_route: /company, invite or company menu switches
                           │                  the admin's active tenant (routing_epoch += 1); other
                           │                  updates are queued to the active tenant
                           │   member?     → queued to that tenant's inbox, legacy handlers stopped
                           │   invite?     → registered as a new worker of that tenant, then queued
                           │   otherwise   → falls through to the legacy bot handlers (unchanged)
                           ▼
          <tenant DB>.telegram_update_inbox (status pending → processing → done/failed/skipped)
                           ▼
   forest-ai-<tenant>-telegram (telegram_tenants/worker.py, never polls)
       uses that instance's telegram_handlers.build_application() and replies with the same token
```

- **Single poller.** Only `bot.py` calls `getUpdates`. Workers only send replies.
- **Isolation.** Tenant envelopes, memberships and worker state live only in that tenant's
  SQLite. A routing or storage error stops the update; it never falls through to legacy writes.
- **Admins** (`FOREST_TELEGRAM_ADMIN_IDS`) can switch companies. Every switch increments
  `routing_epoch` in the routing DB.
  - Inline buttons sent to admins are stamped `ctx:<tenant>:<epoch>|<data>`
    (`telegram_tenants/tenant_runtime.py`).
  - A button from an earlier company context is rejected ("belongs to an earlier company context").
  - The worker strips the prefix before calling the handlers.
  - Edited live-location messages are only accepted when the original message was bound to
    the same tenant and epoch (`telegram_message_bindings`).
- **Workers** join a tenant only if it has an invite code; such a tenant is called "joinable".
  - A worker who already exists in any other operational DB is never silently moved. Those
    DBs are the poller's own DB and every other tenant's DB.
  - "Exists" means a row in `sector_employees`, `sector_vehicles`, `work_sessions` or
    `live_locations`.
- **Flag off** (`FOREST_TENANT_ROUTING` unset or anything other than `1`): `bot.py` does not
  import the router or the package at all. It behaves exactly like the production-tagged
  bot (`prod-2026-11-07-meza-karte`). Tests check this.

## Environment variables

| variable | used by | default | meaning |
|---|---|---|---|
| `FOREST_TENANT_ROUTING` | bot.py | unset (off) | `1` installs the router before all legacy handlers |
| `FOREST_TELEGRAM_TENANTS_FILE` | router, worker | `data/telegram/tenants.json` | tenant config (format: `telegram_tenants/tenants.example.json`) |
| `FOREST_TELEGRAM_ROUTING_DB` | router, worker | `data/telegram/routing.db` | admin company context and message bindings |
| `FOREST_TELEGRAM_LOCK_DIR` | router, worker | `/run/forest-ai-telegram-locks` | per-user `flock` files shared by poller and workers |
| `FOREST_TELEGRAM_ADMIN_IDS` | router, worker | unset → `admin_ids` in the tenants file, else none | admin Telegram user ids, comma/space separated |
| `FOREST_TENANT_INVITE_<KEY>` | router, worker | unset → tenant not joinable | invite code for tenant `<key>`; `<KEY>` is the key upper-cased with non-alphanumerics as `_` (`my-client` → `FOREST_TENANT_INVITE_MY_CLIENT`) |
| `FOREST_TENANT_KEY` | worker | required | the tenant key this worker serves |
| `DB_PATH` | bot.py, router, worker | `data/forest_ai.db` | the poller's own DB. Worker: must equal the tenant's `database` |
| `TELEGRAM_BOT_TOKEN` | bot.py, worker handlers | required | the shared bot token. Never log it |

Relative paths resolve against the code root (the directory that contains
`telegram_tenants/`), not against the working directory. Units should pass absolute paths.

The tenants file has this shape (see `tenants.example.json`):
`{"default_admin_tenant": key, "tenants": {key: {"name", "tenant", "sector", "project", "database"}}}`.
It may also contain `admin_ids`, the live format, which is used only when
`FOREST_TELEGRAM_ADMIN_IDS` is unset.

## Data files (never in git)

| file | content | written by |
|---|---|---|
| tenants file | tenant names, tenant ids, sectors, instance and DB paths (and possibly `admin_ids`) | humans |
| routing DB | `admin_company_context` (active tenant, sector, epoch per admin), `telegram_message_bindings` | router (and worker reads) |
| each tenant DB | `telegram_tenant_memberships`, `telegram_update_inbox`, `telegram_worker_state`, plus normal operational rows written by the tenant handlers | router + worker |
| lock dir | `<telegram user id>.lock` | router + worker |

## Current production layout (2026-11-09, unversioned)

| piece | location |
|---|---|
| main poller | `forest-bot` → `/root/forest_ai/bot.py` (root checkout, hook **not** behind a flag) |
| router | `/root/forest_ai/telegram_tenant_router.py` (untracked; hard-coded tenant, sector, DB paths, invite) |
| package | `/root/forest_ai_telegram/{company_context,tenant_runtime,worker}.py`; the router adds this directory to `sys.path` |
| tenants file | `/root/forest_ai_telegram/config.json` (includes `admin_ids`) |
| routing DB | `/root/forest_ai_telegram/routing.db` |
| workers | `forest-ai-rigas-telegram`, `forest-ai-ingka-telegram` → `python3 /root/forest_ai_telegram/worker.py`, cwd = the instance, `FOREST_TENANT_KEY` in the unit (mirrors in `deploy/systemd/`) |
| worker handlers | `<instance>/telegram_handlers.py`: a copy of `bot.py` with `build_application()` and a generic error message (**still unversioned**, see "Not covered yet") |

The versioned code reproduces the live behaviour when its configuration matches the live
values:
- the same tenants file;
- the same routing DB;
- `FOREST_TENANT_INVITE_INGKA` set to the invite that is hard-coded today;
- admin ids from `config.json`.

The CHECK constraints the router would create match the live tables exactly (verified
read-only on 2026-11-09).

## Cutover plan: NOT EXECUTED, needs human approval

Scope of step 1: **only `forest-bot`**. The code location moves from the untracked root
files to a release built from git. Data stays exactly where it is. The workers are untouched.

### Preconditions
1. `feature/telegram-tenants` is reviewed and merged. The merge commit is tagged
   (for example `bot-tenants-YYYYMMDD`).
2. `telegram_update_inbox` has no `pending` or `processing` rows in either tenant DB.
3. A maintenance moment is agreed. The bot is offline for about 5–10 s during the restart.
   Telegram keeps updates and delivers them after the restart.

### Steps (about 5 minutes)
```sh
TS=$(date -u +%Y%m%dT%H%M%SZ); TAG=bot-tenants-YYYYMMDD
B=/root/forest_ai/data/backups/telegram_cutover_$TS; install -d -m 0700 $B
# 1. Record the current state
systemctl show forest-bot -p MainPID -p WorkingDirectory -p DropInPaths > $B/before.txt
sha256sum /root/forest_ai/bot.py /root/forest_ai/telegram_tenant_router.py /root/forest_ai_telegram/*.py >> $B/before.txt
# Tenant DB paths come from the live tenants file; they are not written down in git.
DBS="/root/forest_ai_telegram/routing.db $(python3 -c 'import json;print(" ".join(t["database"] for t in json.load(open("/root/forest_ai_telegram/config.json"))["tenants"].values()))')"
i=0; for db in $DBS; do i=$((i+1))
  sqlite3 "file:$db?mode=ro" "SELECT name, sql FROM sqlite_master WHERE name LIKE 'telegram_%' OR name LIKE 'admin_%' ORDER BY name" > $B/schema_$i.txt
done
sqlite3 /root/forest_ai_telegram/routing.db ".backup $B/routing.db"; chmod 0600 $B/*
# 2. Build the bot release from git (same mechanism as the API, docs/DEPLOY_RELEASES.md)
R=/root/forest_ai/releases/forest-bot-telegram-tenants-$TS; mkdir -p $R
git -C /root/forest_ai archive $TAG | tar -x -C $R; ln -s /root/forest_ai/data $R/data
# 3. Invite env file: copy the live invite constant without printing it
umask 077; sed -n "s/^INVITE = '\(.*\)'$/FOREST_TENANT_INVITE_INGKA=\1/p" /root/forest_ai/telegram_tenant_router.py > /root/forest_ai_telegram/tenants.env
test "$(wc -l < /root/forest_ai_telegram/tenants.env)" = 1
# 4. Drop-ins (code location + routing env), then restart ONLY forest-bot
printf '[Service]\nWorkingDirectory=%s\n' $R > /etc/systemd/system/forest-bot.service.d/50-bot-release.conf
cp $R/deploy/systemd/forest-bot.service.d/60-telegram-tenants.conf.proposed /etc/systemd/system/forest-bot.service.d/60-telegram-tenants.conf
systemctl daemon-reload && systemctl restart forest-bot
```

### Verification (within 2 minutes; any failure means roll back)
1. `systemctl is-active forest-bot` reports `active`, and the MainPID is new and stays the
   same for 60 s (no restart loop).
2. `readlink /proc/$(systemctl show -p MainPID --value forest-bot)/cwd` returns `$R`.
3. The journal shows "Forest AI Bot started" and no traceback. Mask the token when printing:
   `journalctl -u forest-bot -n 50 | sed -E 's/bot[0-9]+:[A-Za-z0-9_-]+/bot<TOKEN>/g'`.
4. The schema snapshot is unchanged (the router's initialize is a no-op on these tables):
   re-run the `sqlite_master` loop from step 1 into a second directory and `diff -r` it against the `$B/schema_*.txt` files.
5. Functional checks:
   - An admin sends `/company`: the company indicator and menu appear.
   - A non-member test account sends `hello`: it gets the legacy bot reply as before.
   - A tenant member sends a message: a new inbox row appears and goes `pending` → `done`
     (the worker is unchanged).
6. The worker PIDs (`forest-ai-*-telegram`) are unchanged.

### Rollback (under 2 minutes; data needs no rollback)
```sh
rm -f /etc/systemd/system/forest-bot.service.d/50-bot-release.conf \
      /etc/systemd/system/forest-bot.service.d/60-telegram-tenants.conf
systemctl daemon-reload && systemctl restart forest-bot
readlink /proc/$(systemctl show -p MainPID --value forest-bot)/cwd   # → /root/forest_ai
```
This returns the bot to the untouched root checkout, which still has the old `bot.py`
and router. Every schema statement is `IF NOT EXISTS`, `INSERT OR IGNORE` or a conditional
`ADD COLUMN`, so there is nothing to undo in the DBs. `tenants.env` can stay; it is unused
after rollback. Do not restore the routing DB backup unless a separate data recovery is
approved: it would discard admin company switches made after the cutover.

### Step 2 (later, separate approval): workers
The worker units run with `ProtectSystem=strict` and `InaccessiblePaths=/root/forest_ai`.
**They cannot load code from `/root/forest_ai/releases/`.**
Options:
- export `telegram_tenants/` to a path outside `/root/forest_ai` (for example
  `/root/forest_ai_telegram/releases/<tag>/`) and point `ExecStart` there, with absolute
  `FOREST_TELEGRAM_*` variables; or
- relax `InaccessiblePaths`. This weakens tenant isolation and is not recommended.

Before step 2, the instance `telegram_handlers.py` must be versioned (see below).

## Risks

### R1: the main bot writes schema into every tenant DB on each start
`install()` → `initialize()` runs at **every** `forest-bot` start, for **every** tenant in
the tenants file. That includes the Rīgas meži instance DB,
whose application code (574bd97) knows nothing about these tables. These are the
statements:

| target | statement | additive? |
|---|---|---|
| routing DB | `CREATE TABLE IF NOT EXISTS admin_company_context (...)` | yes |
| routing DB | `CREATE TABLE IF NOT EXISTS telegram_message_bindings (...)` | yes |
| routing DB | `INSERT OR IGNORE INTO admin_company_context` for each admin (default tenant, epoch 1) | yes (row; existing rows untouched) |
| routing DB | `chmod 0600` | permission change only |
| lock dir | `mkdir -p` (mode 0700) | yes |
| each tenant DB | `CREATE TABLE IF NOT EXISTS telegram_tenant_memberships (...)` (with `CHECK(tenant=…)`/`CHECK(sector=…)` only for joinable tenants) | yes |
| each tenant DB | `CREATE TABLE IF NOT EXISTS telegram_update_inbox (...)` | yes |
| each tenant DB | `CREATE TABLE IF NOT EXISTS telegram_worker_state (...)` | yes |
| each tenant DB | `ALTER TABLE telegram_update_inbox ADD COLUMN routing_epoch INTEGER NOT NULL DEFAULT 0`, only if the column is missing | yes (nullable-safe default) |
| each tenant DB | `INSERT OR IGNORE INTO telegram_tenant_memberships` for each admin that has a `sector_employees` row in that tenant's sector | yes (row) |

**No statement is non-additive.** There is no `DROP`, `DELETE`, `UPDATE` of existing rows,
column rename or type change. The live Rīgas meži DB already contains all three tables,
`routing_epoch` and one admin membership row. Pre-existing operational tables are only
read (`sector_employees`).

Side effects that still matter:
- **Startup coupling.** If any tenant DB is locked for more than 15 s, or lacks
  `sector_employees`, `initialize()` raises, `bot.py` exits, and systemd restart-loops the
  **main** bot. A client instance can therefore take the main bot down.
- **Missing path creates a file.** `sqlite3.connect()` creates an empty file when a
  configured tenant `database` path does not exist. The next statement then fails, which
  stops the main bot and leaves an empty DB file behind.
- **Cross-instance writes.** The main bot needs write access to every tenant DB. The worker
  units are sandboxed (`ProtectSystem=strict`, `InaccessiblePaths`); the main bot is not.
- **Legacy-identity reads.** On every invite registration the router opens the main DB and
  all other tenant DBs read-only.

### R2: one token, three processes
The poller and all workers use the same `TELEGRAM_BOT_TOKEN`. If a worker ever called
`getUpdates` (for example a handler copy that still calls `run_polling`), Telegram would
split updates between the processes. `worker.py` never polls. Keep it that way.

### R3: lock directory after reboot (unverified)
`/run/forest-ai-telegram-locks` is created by the poller's `initialize()`. If a worker
processes an update before the poller has started after a reboot, `user_lock()` fails.
The update is then marked `failed` (`processing_failed`) and kept for review. Not observed;
derived from the code.

### R4: config contains personal identifiers
The tenants file may contain admin Telegram user ids. Treat it like `.env`: mode 0600,
never in git, never printed.

## Not covered yet
- **`telegram_handlers.py`** (identical in `/root/forest_ai_rm` and `/root/forest_ai_ingka`)
  is a modified copy of `bot.py` (+5/−11 against 574bd97) and is not versioned. Proposal:
  give `bot.py` a `build_application(bot=None)` factory and the generic error message, so
  instances use `bot.py` itself. This is a separate task.
- **Client-specific dashboard changes** (`/api/telegram/positions`, branding) are not in
  core. They are on the private branch `client/ingka`, pending the tenant architecture
  decision.
