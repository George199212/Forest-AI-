# Migration changelog — 2026-11-17 (forest-ai-production-ams3, 64.225.79.80)

Every production-changing action on the new host, with exact rollback.
Read-only tasks (T1 state check, T2 nginx temp-dir audit — no change made) are not logged here.

---

## T4 — Hide FastAPI docs publicly (app.forestaisystems.com)

- **When:** 2026-11-17 13:47 UTC (nginx reload 13:47:25, master PID 960 unchanged)
- **Approved by:** user ("OK, apply T4")
- **Why:** `/docs`, `/redoc`, `/openapi.json` (153 API paths) were served without auth on app.forestaisystems.com.
  Frontend (active release `forest-api-satellite-monitoring-20261117T0521Z`, index.html + assets/*.js) has no reference to openapi/redoc/swagger//docs.
  No real app routes exist under `/docs*`, `/redoc`, `/openapi*` on :8000/:8002/:8004.

**Changes**
1. New file `/etc/nginx/snippets/forest-hide-api-docs.conf` (exact-match 404 for `/docs`, `/redoc`, `/openapi.json`; prefix `^~ /docs/`).
2. `/etc/nginx/sites-available/forest-ai-public.conf`: one line added in the `app.forestaisystems.com` 443 server block, before `location /`:
   `include /etc/nginx/snippets/forest-hide-api-docs.conf;`
   - Backup: `/etc/nginx/sites-available/forest-ai-public.conf.bak-20261117T1347Z`
     (sha256 `801a7568c89ae00b3eac7de43c7604bc65ddd401483420b9ce17d40014bb6f67`)
3. `nginx -t` OK → `systemctl reload nginx`.

**Verification (via `--resolve app.forestaisystems.com:443:127.0.0.1`; DNS still on OLD IP)**
- `/docs`, `/docs/`, `/docs/oauth2-redirect`, `/docs?x=1`, `/redoc`, `/openapi.json` → 404
- `/`, `/api/sectors`, `/assets/logo.png` → 401 (unchanged, auth still enforced)
- apex `/` → 200, www `/` → 301 (unchanged)
- `http://127.0.0.1:8000/docs` → 200 (backend untouched)
- nginx error.log: no new lines

**Rollback**
```bash
cp -a /etc/nginx/sites-available/forest-ai-public.conf.bak-20261117T1347Z /etc/nginx/sites-available/forest-ai-public.conf
rm /etc/nginx/snippets/forest-hide-api-docs.conf
nginx -t && systemctl reload nginx
```

**Follow-up:** rm/ingka server blocks (T3) must include the same snippet.

---

## T6 — Daily SQLite backups, Tier A (local) + rclone install

- **When:** 2026-11-17 13:51–13:55 UTC
- **Approved by:** user ("(a) OK, build Tier A", "apt install rclone is approved", "(d) Delete the /tmp restore-test directory")

**Changes**
1. Deleted `/tmp/forest-restore-test-20261117T1349Z/` (my own T6 restore-test copies; user decision d).
2. `apt-get install --no-install-recommends rclone` → `rclone 1.60.1+dfsg-3ubuntu0.24.04.6` (1 package, no deps/upgrades).
   needrestart restarted nothing (all service PIDs unchanged).
3. New `/usr/local/sbin/forest-db-backup` (root 700, Python, stdlib only). Per DB: sqlite backup API from read-only
   connection → `PRAGMA integrity_check` → gzip → gzip round-trip sha256 check → `manifest.json` (sha256, sizes,
   journal mode, per-table row counts). Output `/root/backups/daily/<YYYY-MM-DDTHHMMZ>/`, umask 077, log
   `/root/backups/daily/backup.log` + journal. Exit ≠0 on any failure. flock against concurrent runs.
   Retention: removes only dirs matching `^\d{4}-\d{2}-\d{2}T\d{4}Z$` older than 14 days.
   DBs: main, satellite, rm, ingka, review (release-local, effective DB_PATH), routing.
4. New `/etc/systemd/system/forest-db-backup.service` (oneshot, UMask 0077, Nice 10, IO idle) and
   `/etc/systemd/system/forest-db-backup.timer` (02:15 UTC daily, Persistent, RandomizedDelaySec 5min); `daemon-reload`, timer enabled.

**Verification**
- Run 2026-11-17T1353Z: all 6 OK, integrity ok, 0.6 s. Independent restore of satellite (WAL) + rm: sha256 matches
  manifest, integrity ok, row counts equal live (8291/8291, 330/330).
- Duplicate run in same minute correctly refused (unit failed, nothing overwritten).
- Retention test: fake `2026-10-01T0000Z` removed, non-matching `2026-10-01-decoy` untouched (then removed manually).
- Source DB mtimes unchanged; no service restarted.

**Rollback**
```bash
systemctl disable --now forest-db-backup.timer
rm /etc/systemd/system/forest-db-backup.service /etc/systemd/system/forest-db-backup.timer /usr/local/sbin/forest-db-backup
systemctl daemon-reload
apt-get remove rclone            # only if off-site is abandoned
# backups in /root/backups/daily/ are left in place (delete manually only if intended)
```

### T6 closure — 2026-11-17 (user decision)

- **DigitalOcean Droplet Backups: DAILY, enabled by user in the DO panel** (not configured or verified from this host).
  This is a whole-disk, crash-consistent image. It is a complement to the SQLite-consistent Tier A copies, not a replacement for them.
- **Tier A (local daily DB backups, 14-day retention): kept as built above.**
  Because `/root/backups/daily/` sits on the droplet disk, the daily droplet backups also carry the most recent consistent DB copies.
- **Off-site (DO Spaces fra1 + rclone crypt): POSTPONED.** No bucket, key, or rclone remote has been configured.
  rclone 1.60.1 stays installed but unconfigured (`/root/.config/rclone/rclone.conf` does not exist).
- **Tier B (photos + config archive): SKIPPED for now.** Its precondition, a working off-site destination, has not been met.

**Remaining risks (accepted for now)**
- No backup leaves DigitalOcean. Droplet backups live in the same DO account, so an account compromise or loss affects production and backups alike.
- Photo directories (`risk_photos`, `work_photos`, `sector_snapshots`, `cadastre`, per instance) are covered only by the droplet backups, with no file-level copy.
- A Tier A failure only shows as a failed systemd unit (`systemctl --failed`, `backup.log`); nothing raises an alert.
- `DBS["review"]` in `/usr/local/sbin/forest-db-backup` is pinned to release `forest-review-geo-20261113T1023Z`, so it must be updated when that release changes. Until then it fails loudly with "source missing".

**T6 status: CLOSED.**

---

## T3 — Client subdomains rm / ingka + certificate expansion

- **When:** 2026-11-17 14:40–14:50 UTC
- **Approved by:** user ("OK, apply T3 steps 1–6")
- **Precondition:** DNS switched by user at GoDaddy (@, app, rm, ingka → 64.225.79.80, TTL 600); verified 14:36 UTC
  on ns27/ns28.domaincontrol.com, 1.1.1.1, 8.8.8.8, 9.9.9.9 (all 5 names incl. www). No AAAA, no CAA.

**Changes**
1. Backup `/root/backups/letsencrypt-20261117T1440Z.tar.gz` (600; full /etc/letsencrypt incl. keys, 39 entries).
2. New `/etc/nginx/sites-available/forest-ai-clients.conf` + symlink in `sites-enabled/`:
   port 80 → 301 https for rm/ingka (step 2, reload 14:40:58), then 443 ssl blocks (step 5, reload 14:41:23):
   rm → `127.0.0.1:8002`, ingka → `127.0.0.1:8004`, proxy directives identical to the app block,
   `include /etc/nginx/snippets/forest-hide-api-docs.conf` (T4 snippet).
   Intermediate backup: `forest-ai-clients.conf.bak-20261117T1441Z` (port-80-only version).
   `forest-ai-public.conf` NOT modified.
3. Certificate expanded with **snap certbot 5.10.0** (`/snap/bin/certbot`; apt `/usr/bin/certbot` is broken, see below):
   ```
   /snap/bin/certbot certonly --nginx --cert-name forestaisystems.com --expand --key-type ecdsa \
     -d forestaisystems.com -d www.forestaisystems.com -d app.forestaisystems.com \
     -d rm.forestaisystems.com -d ingka.forestaisystems.com \
     --deploy-hook "systemctl reload nginx" --non-interactive
   ```
   Staging `--dry-run` first: OK. Real run: OK.
   - Before: `cert1.pem`, serial 063D811D…AD48, SAN app/apex/www, notAfter 2027-02-14 08:30:05 GMT
   - After:  `cert2.pem`, serial 05BAAD61…4C, SAN app/apex/www/rm/ingka, ECDSA, notAfter 2027-02-15 13:42:25 GMT
   - Renewal conf `/etc/letsencrypt/renewal/forestaisystems.com.conf`: `authenticator = nginx`, `installer = nginx`
     (kept), **new** `renew_hook = systemctl reload nginx` (redundant with installer; harmless extra graceful reload).

**Verification** (public hostnames → 64.225.79.80, curl with system CA store; LE HTTP-01 validated port 80 externally)
- rm & ingka: `/`, `/api/sectors` → 401 (`www-authenticate: Basic`, app body `{"detail":"Not authenticated"}`), cert verify=0;
  `/docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json` → 404; http → 301 https.
- Unchanged: app `/` 401, app `/docs` + `/openapi.json` 404, apex 200, www 301 → apex, http apex/app 301.
- `openssl s_client -verify_hostname` for all 5 SNI names: Verify return code 0, serial 05BAAD61…, notAfter 2027-02-15.
- `/snap/bin/certbot renew --dry-run`: "all simulated renewals succeeded" (non-interactive random delay 333 s is normal);
  live cert still cert2.pem, no acme-challenge leftovers in nginx config.
- nginx master PID 960 unchanged, error.log no new lines; no Forest service restarted.

**Renewal ownership (finding)**
- **Renews:** `snap.certbot.renew.timer` (enabled; 01:58 + 16:30 daily) → `snap run certbot.renew` → snap certbot 5.10.0.
  Has not yet fired on this host (first run 2026-11-17 16:30 UTC).
- **Broken, no effect:** `certbot.timer` (apt; 00,12:00 + up to 12 h random) → `/usr/bin/certbot` 2.9.0 crashes on import
  (`AttributeError: module 'lib' has no attribute 'GEN_EMAIL'`) because pip-installed `cryptography 50.0.1` in
  `/usr/local/lib/python3.12/dist-packages` shadows apt `python3-cryptography 41.0.7` used by apt `python3-openssl 23.2.0`.
  Unit fails every run (last 13:36 UTC). **Not changed** (user: propose separately).

**Rollback**
```bash
# nginx (rm/ingka vhosts)
rm /etc/nginx/sites-enabled/forest-ai-clients.conf
nginx -t && systemctl reload nginx
# certificate (normally unnecessary: new cert is a superset)
rm -rf /etc/letsencrypt && tar -C /etc -xzpf /root/backups/letsencrypt-20261117T1440Z.tar.gz
nginx -t && systemctl reload nginx
```
Note: the T4 snippet is now included by forest-ai-clients.conf too — rolling back T4 requires removing those
`include` lines (or the clients symlink) before deleting the snippet.

---

## Certbot cleanup — disable + remove broken apt certbot (proposal A+B)

- **When:** 2026-11-17 ~14:57 UTC
- **Approved by:** user ("apply A+B (show the apt-get remove dry-run first, then apply)")
- **Precondition confirmed:** `/snap/bin/certbot renew --dry-run` (14:44–14:50 UTC) → "Congratulations, all simulated
  renewals succeeded: /etc/letsencrypt/live/forestaisystems.com/fullchain.pem (success)"; staging authz valid for
  app, apex, ingka, rm, www.

**Changes**
- A: `systemctl disable --now certbot.timer` + `systemctl reset-failed certbot.service`.
- B: `apt-get remove -y certbot python3-certbot python3-certbot-nginx` (dry-run: exactly these 3 Remv, 0 installs/upgrades).
  `remove` (not purge) → conffiles kept: `/etc/letsencrypt/cli.ini` (also read by snap certbot) and
  `/etc/cron.d/certbot` (no-op: requires /usr/bin/certbot AND no systemd). No autoremove run.
  pip `cryptography 50.0.1` in /usr/local NOT touched.

**Verification**
- `which certbot` → `/snap/bin/certbot` (also in login shell); `certbot --version` → 5.10.0.
- `snap.certbot.renew.timer`: enabled / active, next 2026-11-17 16:30 UTC. apt `certbot.timer` unit gone.
- Cert unchanged (expiry 2027-02-15 13:42:25); no failed units; Forest + nginx PIDs unchanged.

**Rollback**
```bash
apt-get install certbot python3-certbot-nginx   # (still broken by the pip cryptography conflict, as before)
systemctl enable --now certbot.timer
```

---

## T5 — Bind uvicorn to 127.0.0.1 (one service at a time)

Pre-check (read-only, 2026-11-17 ~14:58 UTC): grep of forest-bot (`/root/forest_ai/*.py`, `services/`), telegram worker
(`/root/forest_ai_telegram`, rm/ingka `telegram_handlers.py`), satellite jobs (`satellite_monitoring/`), active app
releases, nginx, systemd units, env files (key + token only), cron, live connections → **no client reaches 8000–8004
via 0.0.0.0 / 64.225.79.80 / 10.110.0.2 / 10.18.0.5**; nginx proxies to 127.0.0.1 only. Separate finding → T9
(hardcoded OLD-IP dashboard links in bot.py / telegram_handlers.py).

### T5.1 forest-review-api (:8003)
- **When:** 2026-11-17 14:59:26 UTC (restart). **Approved by:** user ("OK, apply T5 for forest-review-api").
- **Change:** new `/etc/systemd/system/forest-review-api.service.d/99-bind-localhost.conf`
  (`ExecStart=` reset + `ExecStart=/usr/local/bin/uvicorn api:app --host 127.0.0.1 --port 8003`); `daemon-reload`; restart.
  Other args identical to previous effective ExecStart; WorkingDirectory (50-review-geo-release.conf) unchanged.
- **Verification:** PID 893 → 39921, active, NRestarts=0; `ss`: `127.0.0.1:8003`; 127.0.0.1:8003 `/`, `/api/sectors`,
  `/assets/logo.png` → 401 (= baseline); `64.225.79.80:8003` and `10.110.0.2:8003` → connection refused (before: 401
  via host-local path); journal: startup complete, no errors; app/rm/ingka 401, apex 200, www 301 unchanged.
- **Rollback:** `rm /etc/systemd/system/forest-review-api.service.d/99-bind-localhost.conf && systemctl daemon-reload && systemctl restart forest-review-api`

### T5.2 forest-rm-api (:8002)
- **When:** 2026-11-17 15:02:51 UTC (restart). **Approved by:** user ("OK, apply T5 for forest-rm-api").
- **Change:** new dir + file `/etc/systemd/system/forest-rm-api.service.d/99-bind-localhost.conf`
  (`ExecStart=` reset + `ExecStart=/usr/local/bin/uvicorn api:app --host 127.0.0.1 --port 8002`); `daemon-reload`; restart.
  Previous effective ExecStart identical except `--host 0.0.0.0`; WorkingDirectory `/root/forest_ai_rm` unchanged.
- **Verification:** PID 894 → 41647, active, NRestarts=0; `ss`: `127.0.0.1:8002`; 127.0.0.1:8002 `/`, `/api/sectors`,
  `/assets/logo.png` → 401; `https://rm.forestaisystems.com/` → 401 (verify=0), `/docs` + `/openapi.json` → 404;
  `64.225.79.80:8002` → connection refused; journal: startup complete, no errors; nginx error.log: no new lines;
  forest-ai-rigas-telegram active, PID 890 unchanged, NRestarts=0, no errors; app/ingka 401, apex 200, www 301, :8003 401.
- **Rollback:** `rm /etc/systemd/system/forest-rm-api.service.d/99-bind-localhost.conf && systemctl daemon-reload && systemctl restart forest-rm-api`

### T5.3 forest-ai-ingka (:8004)
- **When:** 2026-11-17 15:03:44 UTC (restart). **Approved by:** user ("OK, apply T5 for forest-ai-ingka").
- **Change:** new dir + file `/etc/systemd/system/forest-ai-ingka.service.d/99-bind-localhost.conf`
  (`ExecStart=` reset + `ExecStart=/usr/local/bin/uvicorn api:app --host 127.0.0.1 --port 8004`); `daemon-reload`; restart.
  Previous effective ExecStart identical except `--host 0.0.0.0`; WorkingDirectory and Environment
  (PYTHONDONTWRITEBYTECODE, TMPDIR, XDG_CACHE_HOME) unchanged and present in new process.
- **Verification:** PID 889 → 42353, active, NRestarts=0; `ss`: `127.0.0.1:8004`; 127.0.0.1:8004 `/`, `/api/sectors`,
  `/assets/logo.png` → 401; `https://ingka.forestaisystems.com/` → 401 (verify=0), `/docs` + `/openapi.json` → 404;
  `64.225.79.80:8004` → connection refused; journal clean; forest-ai-ingka-telegram active, PID 888 unchanged, no errors.
  nginx error.log: 6× `connect() failed (111)` 15:03:44–45 during restart window, all from scanner `2.25.212.104`
  (UA `monitord-discovery/1.0`), which got 401 again at 15:03:46. Expected restart blip; no user impact observed.
- **Rollback:** `rm /etc/systemd/system/forest-ai-ingka.service.d/99-bind-localhost.conf && systemctl daemon-reload && systemctl restart forest-ai-ingka`

### T5.4 forest-api (:8000, main app)
- **When:** 2026-11-17 15:06:00 UTC (restart). **Approved by:** user ("OK, apply T5 for forest-api").
- **Change:** new `/etc/systemd/system/forest-api.service.d/99-bind-localhost.conf`
  (`ExecStart=` reset + `ExecStart=/usr/local/bin/uvicorn api:app --host 127.0.0.1 --port 8000`); `daemon-reload`; restart.
  Drop-in order after reload: 50-meza-karte, 70, 90, 95, 96, 97-satellite-monitoring, 98-satellite-monitoring-release,
  **99-bind-localhost**, geodata.conf (Environment only) → 99 wins for ExecStart.
- **Pre-restart check (PASS):** effective ExecStart `--host 127.0.0.1 --port 8000`; WorkingDirectory still
  `/root/forest_ai/releases/forest-api-satellite-monitoring-20261117T0521Z`; Environment keys unchanged
  (FOREST_GPS_VIOLATIONS_DAYS, SAT_DATA_DIR, SAT_DB_PATH, SAT_RASTER_DIR, FOREST_GEODATA_MANIFEST).
- **Verification:** PID 891 → 43619, active, NRestarts=0; first response 3.9 s after restart; process cwd = release
  above, all 5 env keys present; `ss`: `127.0.0.1:8000`; 127.0.0.1:8000 `/`, `/api/sectors`, `/assets/logo.png` → 401;
  `https://app.forestaisystems.com/` → 401 (verify=0), `/docs`, `/redoc`, `/openapi.json` → 404;
  `64.225.79.80:8000` and `10.110.0.2:8000` → connection refused; journal: clean shutdown of 891, startup complete,
  `Uvicorn running on http://127.0.0.1:8000`, no errors, no `risk_ai_worker tick failed`; risk AI worker thread is started
  unconditionally in the startup hook (api.py:124) — no RUNNING items existed before restart (17 NULL, 2 DONE);
  nginx error.log: no new lines; forest-bot PID 892 unchanged; all other units active; rm/ingka 401, apex 200, www 301;
  no failed units.
- **Rollback:** `rm /etc/systemd/system/forest-api.service.d/99-bind-localhost.conf && systemctl daemon-reload && systemctl restart forest-api`

### T5 summary — all four uvicorn backends now localhost-only
```
127.0.0.1:8000 forest-api        PID 43619
127.0.0.1:8002 forest-rm-api     PID 41647
127.0.0.1:8003 forest-review-api PID 39921
127.0.0.1:8004 forest-ai-ingka   PID 42353
```
Public/private IPs on 8000–8004 refuse connections even from the host itself; external access only via nginx 80/443.
**T5 status: CLOSED.**

---

## T9 — Telegram dashboard links: hardcoded OLD IP → per-instance DASHBOARD_PUBLIC_URL

- **When:** 2026-11-17 15:09–15:12 UTC. **Approved by:** user ("OK, apply T9").
- **Why:** bot replies linked to `http://164.90.188.136:8000` (OLD server, unreachable; plain HTTP; port 8000 closed).

**Pre-checks**
- git: `/root/forest_ai` (master, HEAD 84cb00b) — `bot.py` already had an uncommitted 3-line addition in `main()`
  (~l.1836, not touching the IP lines; file mtime 2026-10-29 < forest-bot start → already live). Preserved; no
  commit/branch/stash. `/root/forest_ai_rm`, `/root/forest_ai_ingka`, `/root/forest_ai_telegram`: not git repos.
- Tenant workers (`/root/forest_ai_telegram/worker.py`) import `telegram_handlers` from their cwd (rm / ingka).
- Live files re-verified against the reviewed diff immediately before applying (unchanged).

**Changes**
1. Code (identical hunks in all three; rm/ingka files byte-identical before and after):
   `/root/forest_ai/bot.py`, `/root/forest_ai_rm/telegram_handlers.py`, `/root/forest_ai_ingka/telegram_handlers.py`
   - read `DASHBOARD_PUBLIC_URL` once at import (strip + trailing `/` removed); if empty → `logging.warning(...)`,
     links omitted, **no IP fallback**; helper `_dashboard_link_suffix()`.
   - "📋 Открыть дашборд" inline button only if set; both "🗺 <url>" reply lines only if set.
   - Behaviour test (AST-extracted reply expressions): URL set → text identical to before except URL; unset → no link line.
   - `bot.py` vs HEAD now +20/−4 (3 pre-existing + 17/−4 from T9).
2. Env (one line appended each; key absent before; perms 600 kept):
   `/root/forest_ai/.env` → `DASHBOARD_PUBLIC_URL=https://app.forestaisystems.com`
   `/root/forest_ai_rm/.env` → `DASHBOARD_PUBLIC_URL=https://rm.forestaisystems.com`
   `/root/forest_ai_ingka/.env` → `DASHBOARD_PUBLIC_URL=https://ingka.forestaisystems.com`
3. Backups (`.bak-20261117T1509Z`, owner/mode preserved): the 3 code files and the 3 `.env` files above.
4. Restarts, one at a time, each verified 30 s:
   - forest-bot 892 → 46216 (15:10:12)
   - forest-ai-rigas-telegram 890 → 46309 (15:10:56)
   - forest-ai-ingka-telegram 888 → 46864 (15:11:57)
   Each: active, NRestarts=0, `DASHBOARD_PUBLIC_URL` present in /proc environ with the instance URL, 0 "not set"
   warnings, 0 traceback/error/409 lines, `Application started`. No failed units; APIs/nginx untouched.
   Not tested end-to-end (would need a real boundary-plan upload in Telegram).

**Rollback (per instance; example main)**
```bash
TS=20261117T1509Z
cp -a /root/forest_ai/bot.py.bak-$TS /root/forest_ai/bot.py
cp -a /root/forest_ai/.env.bak-$TS /root/forest_ai/.env
systemctl restart forest-bot
# rm:    /root/forest_ai_rm/{telegram_handlers.py,.env}.bak-$TS    -> systemctl restart forest-ai-rigas-telegram
# ingka: /root/forest_ai_ingka/{telegram_handlers.py,.env}.bak-$TS -> systemctl restart forest-ai-ingka-telegram
```
Note: restoring a `.env` backup also drops any later edits to that file — prefer deleting just the
`DASHBOARD_PUBLIC_URL=` line if the file changed since.

**Remaining OLD-IP references (not changed)**
- `scripts/verify_nationwide_registration.py:64`, `scripts/verify_vmd_cadastral_registration.py:15` (untracked manual
  tools) — send DASHBOARD_USERNAME/PASSWORD to `http://164.90.188.136:8000` → should be `http://127.0.0.1:8000`.
- Unused copies `/root/forest_ai_rm/bot.py`, `/root/forest_ai_ingka/bot.py` (3 each; no service runs them).
- Docs/evidence: ARCHITECTURE.md, CURRENT_STATUS.md, 15 files in docs/ (+ CLIENT_INSTANCES.md in rm/ingka), 3 in docs/evidence/.
