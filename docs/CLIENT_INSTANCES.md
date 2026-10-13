# Client instances (separate accounts)

Status: implemented 2026-10-13, first instance: Rīgas meži (demo).

## Why instances, not multi-tenancy

Forest AI is single-tenant in code:

- one HTTP Basic Auth login for the whole app (`api.py::verify_credentials`);
- no `organization_id` on operational tables (`sectors`, `risks`, `work_photos`, …);
- `organization_id` exists only on the Integration Layer tables, and is always `1`
  (`api.py::DEFAULT_ORG_ID`, documented there as "not an enforced access boundary").

A client account is therefore **a second copy of the same code in its own directory**,
with its own `.env`, `data/` (SQLite DB + photos), port and systemd unit.
No application code was changed to support this: every data path in the code is
relative to the working directory, and DB path and login come from `.env`.

Why a separate code directory and not just a separate `WorkingDirectory`:
`services/photo_compare.py` resolves photo paths relative to the **code**
directory (`APP_DIR = dirname(database.__file__)`), not the working directory.
Sharing code between instances would make the client's photo comparison read
the main instance's files.

| | Main instance | Rīgas meži instance |
|---|---|---|
| Directory | `/root/forest_ai` | `/root/forest_ai_rm` |
| Port | 8000 | 8002 (8001 is the orphaned test uvicorn) |
| systemd | `forest-api.service`, `forest-bot.service` | `forest-rm-api.service` only |
| DB / photos | `data/` of main | own `data/` |
| Login | main `.env` | own, generated |
| Telegram bot | yes | **none** (decision 2026-10-13) |
| Anthropic / Sentinel keys | own | copied from main (shared accounts and costs) |
| `INTEGRATION_CREDENTIALS_KEY` | own | own, generated |

## Create the Rīgas meži instance

Prerequisite: `scripts/clone_sector_instance.py` and `deploy/create_client_instance.sh`
exist in `/root/forest_ai` (pull the commit or scp both files).

```bash
# 1. Exact sector name (spelling matters)
python3 /root/forest_ai/scripts/clone_sector_instance.py --source-root /root/forest_ai --list-sectors

# 2. Create (interactive: dry run, then confirmation at each step)
bash /root/forest_ai/deploy/create_client_instance.sh \
     --slug rm --org-name "Rīgas meži" --org-slug rigas-mezi \
     --sector "BIK-001" --port 8002
```

The script prints the URL, login and generated password at the end.
The password is stored only in `/root/forest_ai_rm/.env`.

### Workers registered under another sector

If the kept sector's sessions, live locations or routes were recorded by a worker whose
`sector_employees` row belongs to another sector, the dry run reports dangling
`employee_id` references. Pass that worker's id:

```bash
... --sector "BIK-001" --include-employee 2
```

The row is copied and re-assigned to the first kept sector **in the copy only**
(the main DB is not changed), so the client never sees another sector's name.
The re-assignment is listed in the dry-run warnings and in `instance_manifest.json`
(`reassigned_employees`).

### What is copied

- Code: exactly what runs in `/root/forest_ai` (rsync, without `data/`, `.env`, `*.db`, caches, `*.bak_*`).
- Data: a consistent snapshot of the main DB (SQLite backup API, source opened read-only),
  filtered to the chosen sector(s):
  - every table with a `sector` column → only rows of the kept sector;
  - `sectors` → only the kept sector;
  - children (`risk_events`, `snapshot_risks`, `risk_conclusions`, `photo_cmp_*`,
    `boundary_plans`, `boundary_plan_points`) → only rows whose parent was kept;
  - all `integration*` tables and `weighbridge_records` → emptied (no credentials travel);
  - `organizations` → one row, renamed to the client;
  - `ai_inspector_analyses` with `scope='all'` (`sector IS NULL`) → removed, they describe other sectors.
- Files referenced by kept rows (work photos, risk photos, snapshots, plans).
- An audit manifest: `data/instance_manifest.json` (source DB hash, rows before/after, files, warnings).

### Guarantees built into the copy script

- Dry run by default; `--apply` refuses to overwrite an existing target DB.
- A table without a copy rule stops the script (new tables are never copied unfiltered).
- Dangling references (kept row pointing at a dropped row) block `--apply`
  unless `--allow-dangling` is given after review.
- `PRAGMA integrity_check` must return `ok`.

## Updating code

The client instance does not update itself when the main one is deployed.
After deploying to `/root/forest_ai`:

```bash
bash /root/forest_ai/deploy/create_client_instance.sh --slug rm --update-code
```

This syncs code only and restarts `forest-rm-api.service`. `data/` and `.env` are untouched.
New tables are created by `init_db()` on startup, as in the main instance.

## Known limitations (accepted for the demo)

- No Telegram bot: dashboard buttons that send Telegram messages return
  `502 Telegram send failed`. New field data for the client (photos, GPS) still
  arrives through the main bot into the **main** instance.
  To add a bot: new token from @BotFather → `TELEGRAM_BOT_TOKEN` in the client `.env` →
  a `forest-rm-bot.service` derived from `forest-bot.service`. The bot's dashboard link
  is hardcoded to `http://164.90.188.136:8000` in `bot.py` and must be made configurable first.
- Plain HTTP on a raw IP and port, same as the main instance. Use HTTPS on a subdomain
  before giving the client their own login for real use.
- Shared Anthropic and Sentinel accounts: usage and cost are not separated per client.
- Same server: a crash or full disk affects both instances.

## Removing an instance

```bash
systemctl disable --now forest-rm-api.service
rm /etc/systemd/system/forest-rm-api.service && systemctl daemon-reload
# keep a backup of /root/forest_ai_rm/data before deleting the directory
```
