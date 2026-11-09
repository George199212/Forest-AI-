# Agent rules: Forest AI

These rules apply to every AI coding agent working on this repository. `AGENTS.md` (read by
Codex) and `CLAUDE.md` (read by Claude Code) must stay identical; change both together.

Production runs on this same VPS. Several agents may be working in parallel. The rules
below protect production and each other's work.

## 1. Where to work

- Work only in a git worktree at `/root/wt/<task-slug>`, on branch `feature/<task-slug>`
  created from `origin/master`:
  ```sh
  git -C /root/forest_ai fetch origin
  git -C /root/forest_ai worktree add /root/wt/<task-slug> -b feature/<task-slug> origin/master
  ```
- Never edit these paths, not even "temporarily":
  - `/root/forest_ai` (the root checkout)
  - existing folders in `/root/forest_ai/releases/` (see "Release folders" below)
  - `/root/forest_ai/data/*`
  - `/root/forest_ai_rm`
  - `/root/forest_ai_ingka`
  - `/root/forest_ai_review`
  - `/root/forest_ai_telegram`
  - `/etc/systemd/*`
- Never restart, stop or reload services. Deployment is a separate step that a human
  approves; see `docs/DEPLOY_RELEASES.md`. Port 8000 is served from a `releases/` folder,
  not from the repo root.

### Release folders

- Agents MAY create NEW release folders in `/root/forest_ai/releases/`. Never modify or delete
  existing ones.
- Production must never run from a worktree path (`/root/wt/...`) or any other temporary path.
- Activation (drop-in change + restart) ONLY after explicit human OK in the chat.

## 2. Data and secrets

- The production database and geodata are read-only for agents: `data/forest_ai.db`,
  `data/geodata/**` and `data/vmd/**`. For tests, copy what you need to `/tmp`. Open
  originals read-only (`?mode=ro`) if you must read them in place.
- Never commit any of these:
  - `.env` or any environment file
  - `*.db` or `*.sqlite`
  - `data/`
  - photos
  - catalogue files (VMD/VZD downloads, extracts and SQLite catalogues)
  - evidence images (`docs/evidence/*`; only `docs/evidence/README.md` is versioned)
- Never print secrets: not in output, logs, commits, docs or test fixtures. Refer to
  variables by NAME only. When showing service logs, mask the Telegram bot token.

## 3. How to work

1. Inspect the code and data, then find the root cause, then make the smallest safe
   change, then test, then document.
2. Keep these four things distinct in code, data and reports:
   raw evidence, processed data, AI interpretation, and human decision.
3. Missing data never becomes `0`. Use `NULL`/`None`/"unknown" and show it as missing.
4. Do not invent APIs, tables, endpoints or data sources. If something is not in the code or
   in official documentation, say so and stop.
5. Do coordinate conversions only with `pyproj` or `services/geodata/forestry_io.py`. Never
   call or copy `lks92_to_wgs84()` / `_lks92_to_wgs84()`; that approximation is off by
   150–190 km.

## 4. How every task ends

- `git status` in the worktree is clean.
- Changes are in logical commits, each with a clear message.
- The feature branch is pushed: `git push origin feature/<task-slug>`. Never push to
  `master`, and never force-push.
- The final report contains:
  - the branch name
  - the list of commits
  - the tests that were run, with their exact results (failures quoted verbatim)
  - what was NOT verified
