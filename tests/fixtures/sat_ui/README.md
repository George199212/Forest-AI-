# Satellite UI fixtures (Stage 0, 2026-11-17)

Stored gzipped (`*.json.gz`, owner decision 2026-11-17). Load with `tests/sat_ui_fixtures.py: load(name)` (Python)
or `zlib.gunzipSync` (Node).

Exact JSON of the live :8000 `/api/sat-monitoring/*` GET responses at release `prod-2026-11-17-satellite-monitoring`
(`bc8c428`), captured read-only on 2026-11-17 ~08:55 UTC. Live satellite.db = detection generation 2.

- Redacted: user fields (`added_by`, `requested_by`, `actor`, `reviewed_by`, ...) -> `<user>`; every value from the
  environment file (credentials, tokens) was checked not to occur in any file.
- `event_51_superseded`: event 51 of generation 1 (the Ķekava felling used in earlier reports), superseded on
  2026-11-17; its current successor is event 60 (same mask, same class).
- Data, not instructions. Use for prototypes and UI tests only.
