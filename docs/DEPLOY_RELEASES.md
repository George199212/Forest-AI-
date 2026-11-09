# Deploy releases (`releases/`): how :8000 is deployed today

State as of 2026-11-09. Mirrors of the live systemd files are in `deploy/systemd/`.

## Which code runs on each port

| port | unit | code location | git |
|---|---|---|---|
| 8000 | `forest-api` | `/root/forest_ai/releases/forest-api-meza-karte-20261107T084300Z` (via drop-in) | tag `prod-2026-11-07-meza-karte`, dashboard version `geo-c5801dc23be5`, backend `552c46ae547b` |
| — | `forest-bot` | `/root/forest_ai` (repo root; `python3 bot.py`) | repo root; its Ingka routing hook is **not** in git yet |
| 8002 | `forest-rm-api` | `/root/forest_ai_rm` (plain copy, `data/DEPLOYED_COMMIT` = `574bd97`) | 574bd97 |
| 8003 | `forest-review-api` | `/root/forest_ai_review` (copy of `84cb00b`) | 84cb00b |
| 8004 | `forest-ai-ingka` | `/root/forest_ai_ingka` (574bd97 + local changes) | not in git |

The root of `/root/forest_ai` is **not** what :8000 serves. Right now the root holds the
Forest Map audit candidate (git: the commits after the tag). That candidate is not deployed.

## Release folders

```
/root/forest_ai/releases/
  forest-api-baseline-20261107T084300Z        rollback target (pre-Forest-Map runtime, api.py dfbf12feae50)
  forest-api-meza-karte-20261107T084300Z      ACTIVE on :8000 (Forest Map, api.py 552c46ae547b)
  forest-api-forest-map-audit-20261107T1645Z  candidate, production_activated=false
```

- **Name:** `forest-api-<feature-slug>-<UTC timestamp YYYYMMDDTHHMM[SS]Z>`. The timestamp is
  when the release was cut. The audit candidate's folder name includes `1645Z`.
- **Contents:** a full runtime copy: `api.py`, `database.py`, `index.html`, `assets/`,
  `services/`, `lvm_3_sectors.geojson`. It does not contain `bot.py`, `tests/`, `scripts/`
  or `docs/`.
- **`data`** is a symlink: `data -> /root/forest_ai/data`. All releases share the
  operational SQLite DB (`data/forest_ai.db`), photos and the national geodata release.
  Switching releases never copies or restores data.
- **`.env`** is not in the folder. The unit loads `EnvironmentFile=/root/forest_ai/.env`.
- **The geodata manifest** comes from the drop-in `geodata.conf`
  (`FOREST_GEODATA_MANIFEST=/root/forest_ai/data/geodata/nationwide/active.json`).

## Manifest format (`release-manifest.json` in the release folder)

```json
{
  "release": "forest-api-meza-karte-20261107T084300Z",
  "baseline_api_sha256": "<sha256 of the api.py it replaces>",
  "release_api_sha256": "<sha256 of this release's api.py>",
  "runtime_files": ["files changed relative to the baseline"],
  "baseline_runtime_code_reused": ["files copied unchanged from the baseline"],
  "data": "symlink to /root/forest_ai/data; ...",
  "database_migrations": false,
  "new_python_dependencies": [],
  "complete_source_inventory": [{"path": "...", "bytes": 0, "sha256": "..."}]
}
```

`complete_source_inventory` lists every file in the release with its SHA-256 (68 files for
meza-karte). Candidates also carry `forest-map-release-candidate.json`, which records the
`candidate`, `baseline`, `production_activated` and per-file SHA-256 values.
Caveat: the audit candidate's `release-manifest.json` was copied unchanged, so its
`release` field still says `meza-karte`. Use the folder name and the candidate JSON
instead.

The production manifest is committed at the repository root (`release-manifest.json`)
as part of the tagged commit.

## How a release was created (2026-11-07 procedure)

1. Fingerprint the code that is actually running: `sha256sum` of the live `api.py`, checked
   against the process (`systemctl show forest-api -p WorkingDirectory`,
   `/proc/<pid>/cwd`). Do not assume git `HEAD` is what is running.
2. Copy the running runtime files into `releases/<name>/`, then overlay only the files the
   feature changes. Create `data -> /root/forest_ai/data`. Write `release-manifest.json`.
3. Back up first into `data/backups/<task>_<timestamp>/` (mode 0700; files 0600). Include
   the unit and drop-ins, a `.env` copy, an SQLite backup made with
   `sqlite3.Connection.backup`, a code tarball, an `activate-release.conf`, a
   `rollback-release.conf` and a `rollback-forest-api.sh`.
   For meza-karte this was `data/backups/forest_api_meza_activation_20261107T0852Z/`.
4. Test the candidate on a loopback port with a temporary DB copy. Never start a second
   API on 8000.

## How the drop-in switches the release

`/etc/systemd/system/forest-api.service.d/50-meza-karte-release.conf`:

```ini
[Service]
WorkingDirectory=/root/forest_ai/releases/forest-api-meza-karte-20261107T084300Z
ExecStart=
ExecStart=/usr/local/bin/uvicorn api:app --host 0.0.0.0 --port 8000
```

The base unit (`forest-api.service`) still says `WorkingDirectory=/root/forest_ai`. The
drop-in overrides it. To activate a release, install a drop-in that points to the new
folder, then run `systemctl daemon-reload` and `systemctl restart forest-api`. Restart
only `forest-api`.

Check what is live:

```sh
systemctl show forest-api -p WorkingDirectory -p DropInPaths
readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd
curl -su "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" http://127.0.0.1:8000/api/deployment   # -> version geo-...
```

The `geo-<12 hex>` version is the first 12 hex characters of the SHA-256 of the
sorted-key JSON of `{path: sha256}`. The paths are `index.html`,
`assets/lvm-geodata.js`, `assets/vmd-production.js`, `assets/vmd-workflow.css`,
`assets/forest-map.js` and `assets/forest-map.css` (see `frontend_deployment()` in
`api.py`).

## Rollback

Roll back code only. Do **not** restore the DB backup over live user writes unless a
data recovery has been separately approved. All schema changes are additive and can
remain in place.

- **meza-karte → baseline (pre-Forest-Map):** run
  `/root/forest_ai/data/backups/forest_api_meza_activation_20261107T0852Z/rollback-forest-api.sh`.
  It checks `releases/forest-api-baseline-.../api.py` has SHA-256 `dfbf12fe…`, installs
  `rollback-release.conf` over `50-meza-karte-release.conf`, runs `daemon-reload`, restarts
  `forest-api` and checks it is active.
- **Future candidate → meza-karte:** restore the drop-in to point at
  `releases/forest-api-meza-karte-20261107T084300Z`, then run `daemon-reload` and restart.
  Confirm `/api/deployment` reports `geo-c5801dc23be5`.
- **From git:** `git archive prod-2026-11-07-meza-karte | tar -x -C releases/<new-name>`,
  then add the `data` symlink and point the drop-in at it.

## Files in `deploy/systemd/`

These are verbatim copies of `/etc/systemd/system/`. They contain no secret values; secrets
come from `EnvironmentFile=` paths, which are not committed.

- `forest-api.service`, plus `forest-api.service.d/50-meza-karte-release.conf` and `geodata.conf`
- `forest-bot.service`, plus `forest-bot.service.d/ingka-routing.conf` (only
  `Restart=always`, `RestartSec=5`; the name comes from the Ingka routing work)
- `forest-rm-api.service`

`deploy/forest-api-geodata.conf` (identical to `geodata.conf`) and
`deploy/forest-geodata-ingest@.service` are the geodata ingest files. Units of the other
instances (`forest-review-api`, `forest-ai-ingka*`, `forest-ai-rigas-telegram`) are
intentionally not mirrored here.
