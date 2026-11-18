#!/bin/bash
# Stage 2/3 sandbox = exactly the release candidate: git archive of feature/sectors-workspace (no fixture URL, no Stage 5
# overlay). Writes only under /root/sectors_sandbox/app. Restart start.sh afterwards (a running server keeps the old cwd).
set -euo pipefail
SB=/root/sectors_sandbox; WT=/root/wt/sectors-workspace; REV=${1:-HEAD}
rm -rf $SB/app && mkdir -p $SB/app
git -C $WT archive "$REV" | tar -x -C $SB/app
ln -sfn $SB/data $SB/app/data
echo "sandbox app = $(git -C $WT rev-parse --short $REV) (release candidate); restart the sandbox"
