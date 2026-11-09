#!/bin/bash
# temp server from the worktree, localhost only, /tmp DB copy, read-only national geodata
S=/tmp/claude-0/-root/c75af14b-759a-45ae-99cc-445b50e7cd32/scratchpad/finish
cd $S/stage && exec choom -n 900 -- env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 \
  DASHBOARD_USERNAME=audit DASHBOARD_PASSWORD=audit-local-only DB_PATH=$S/data/forest_ai.db FOREST_MAP_CACHE_ROOT=$S/fmcache \
  FOREST_GEODATA_MANIFEST=/root/forest_ai/data/geodata/nationwide/active.json PHOTOS_DIR=$S/data/photos \
  nice -n 10 /usr/local/bin/uvicorn api:app --host 127.0.0.1 --port 8011 --log-level warning
