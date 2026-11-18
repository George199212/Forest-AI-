#!/bin/bash
# Sectors workspace Stage 1 sandbox. Binds ONLY 127.0.0.1:8010. View: ssh -L 8010:127.0.0.1:8010 root@64.225.79.80
# App = Stage 5 head 3068e99 (git archive) + feature/sectors-workspace prototype files; DBs = .backup copies (data/SHA256SUMS).
# Private mount namespace: /root is READ-ONLY except /root/sectors_sandbox. Test-only Basic Auth in .sandbox_auth
# (NOT the production credentials). Raster files are read from the live raster dir, read-only.
set -euo pipefail
S=/root/sectors_sandbox; PORT=${SANDBOX_PORT:-8010}
if ss -ltn "sport = :$PORT" | grep -q "$PORT"; then echo "port $PORT already in use"; exit 1; fi
exec unshare -m --propagation private bash -c '
set -euo pipefail
S=/root/sectors_sandbox; PORT='"$PORT"'
mount --bind /root /root && mount -o remount,bind,ro /root
mount --bind $S $S && mount -o remount,bind,rw $S
U=$(sed -n 1p $S/.sandbox_auth); P=$(sed -n 2p $S/.sandbox_auth)
cd $S/app
exec env -i PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 HOME=$S \
  DASHBOARD_USERNAME="$U" DASHBOARD_PASSWORD="$P" \
  DB_PATH=$S/data/forest_ai.db \
  SAT_DATA_DIR=$S/data SAT_DB_PATH=$S/data/satellite.db SAT_RASTER_DIR=/root/forest_ai_satellite_data/satellite \
  FOREST_GEODATA_MANIFEST=/root/forest_ai/data/geodata/nationwide/active.json \
  SAT_GEODATA_ACTIVE=/root/forest_ai/data/geodata/nationwide/active.json \
  /usr/local/bin/uvicorn api:app --host 127.0.0.1 --port $PORT >> $S/logs/uvicorn-$PORT.log 2>&1
'
