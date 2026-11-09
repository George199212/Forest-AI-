#!/bin/bash
# usage: run_server.sh <tree> <port>  — temp audit server, localhost only, no secrets
T=$1; P=$2
cd "$T" && exec env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 \
  DASHBOARD_USERNAME=audit DASHBOARD_PASSWORD=audit-local-only \
  DB_PATH="$T/data/forest_ai.db" FOREST_MAP_CACHE_ROOT="$T/fmcache" \
  FOREST_GEODATA_MANIFEST=/root/forest_ai/data/geodata/nationwide/active.json \
  /usr/local/bin/uvicorn api:app --host 127.0.0.1 --port "$P" --log-level warning
