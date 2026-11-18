#!/bin/bash
# Rebuild the sandbox app: Stage 5 head (git archive) + this branch's sectors prototype + index.html hooks.
# Usage: build_sandbox.sh [STAGE5_REV=3068e99]. Writes only under /root/sectors_sandbox/app.
set -euo pipefail
SB=/root/sectors_sandbox; WT=/root/wt/sectors-workspace; REV=${1:-3068e99}
rm -rf $SB/app && mkdir -p $SB/app
git -C /root/wt/satellite-workspace archive "$REV" | tar -x -C $SB/app
git -C $WT diff bc8c428 -- index.html > $SB/index.patch
python3 - "$SB/app/index.html" "$SB/index.patch" <<'PY'
import re, subprocess, sys
from pathlib import Path
idx, patch = Path(sys.argv[1]), Path(sys.argv[2]).read_text()
# drop the include hunk (Stage 5 has its own include lines there) and apply the rest with offsets
hunks = re.split(r'(?m)^(?=@@ )', patch)
head, body = hunks[0], [h for h in hunks[1:] if 'sectors-cards.js' not in h]
Path('/tmp/sc_rest.patch').write_text(head + ''.join(body))
subprocess.run(['patch', '-p1', '--no-backup-if-mismatch', '-d', str(idx.parent), '-i', '/tmp/sc_rest.patch'], check=True)
s = idx.read_text(encoding='utf-8'); a = '<script src="/assets/sat-workspace.js"></script>\n'
assert s.count(a) == 1 and 'sectors-cards' not in s
s = s.replace(a, a + '<link rel="stylesheet" href="/assets/sectors-cards.css">\n'
              '<script>window.SECTOR_CARDS_URL="/assets/sector-cards-fixture.json"; /* SANDBOX ONLY (Stage 1 fixture) */</script>\n'
              '<script src="/assets/sectors-cards.js"></script>\n')
idx.write_text(s, encoding='utf-8')
PY
cp $WT/assets/sectors-cards.js $WT/assets/sectors-cards.css $SB/app/assets/
cp $WT/tests/fixtures/sectors_ui/sector_cards.json $SB/app/assets/sector-cards-fixture.json
ln -sfn $SB/data $SB/app/data
echo "NOTE: restart the sandbox (start.sh) — a running server keeps the deleted app dir as its cwd"
echo "sandbox app rebuilt from $REV + $(git -C $WT rev-parse --short HEAD) (+ working tree)"
