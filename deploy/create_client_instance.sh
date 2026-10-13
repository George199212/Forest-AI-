#!/usr/bin/env bash
# Create a separate Forest AI instance (client account) on THIS server.
#
# What it does
#   1. Copies the code that is RUNNING in the main instance (not git: changes
#      deployed with scp may not be committed) into a new directory.
#   2. Seeds data/ with only the chosen sector(s) via scripts/clone_sector_instance.py.
#   3. Writes a new .env: own dashboard login, own integration key, no Telegram bot.
#   4. Creates a systemd unit for the API only, derived from forest-api.service,
#      on its own port.
#
# What it never does
#   - restart, stop or edit forest-api.service / forest-bot.service
#   - modify the main instance's DB, files or .env
#   - start a Telegram bot (one token cannot be polled by two processes)
#
# Usage (as root, on the server):
#   bash /root/forest_ai/deploy/create_client_instance.sh \
#        --slug rm --org-name "Rīgas meži" --org-slug rigas-mezi \
#        --sector "BIK-001" --port 8002
#
# Update the client instance's code later (data and .env untouched):
#   bash /root/forest_ai/deploy/create_client_instance.sh --slug rm --update-code

set -euo pipefail

MAIN_DIR="/root/forest_ai"
MAIN_UNIT="forest-api.service"
SLUG=""; ORG_NAME=""; ORG_SLUG=""; PORT=""; UPDATE_CODE=0
SECTORS=()
EMPLOYEES=()

while [ $# -gt 0 ]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2 ;;
    --org-name) ORG_NAME="$2"; shift 2 ;;
    --org-slug) ORG_SLUG="$2"; shift 2 ;;
    --sector) SECTORS+=("$2"); shift 2 ;;
    --include-employee) EMPLOYEES+=("$2"); shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --main-dir) MAIN_DIR="$2"; shift 2 ;;
    --update-code) UPDATE_CODE=1; shift ;;
    -h|--help) sed -n 2,24p "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ "$SLUG" =~ ^[a-z0-9-]+$ ]] || { echo "ERROR: --slug must be lowercase letters/digits/dashes" >&2; exit 2; }
TARGET_DIR="${MAIN_DIR}_${SLUG}"
UNIT="forest-${SLUG}-api.service"

confirm() { read -r -p "$1 [y/N] " a; [[ "$a" == "y" || "$a" == "Y" ]]; }

sync_code() {
  # Code only. data/, .env, databases, caches and backups are never copied.
  # Excludes mirror .gitignore plus .git and ad-hoc files that may mention other
  # sectors. --delete-excluded also removes them from an existing client instance.
  # P (protect) rules MUST come first: with --delete-excluded rsync would otherwise
  # delete the client's own data/ and .env, which are excluded from the copy.
  rsync -a --delete --delete-excluded \
    --filter 'P /data/' --filter 'P /.env' --filter 'P /assets/' \
    --exclude 'data/' --exclude '.env' --exclude '*.db' --exclude '*.db-*' \
    --exclude '__pycache__/' --exclude '*.pyc' --exclude 'venv/' --exclude '*.bak_*' \
    --exclude '*.bak' --exclude '*.log' --exclude '*.patch' --exclude '*.zip' \
    --exclude '.git/' --exclude '.claude/' --exclude '.serena/' --exclude '.headroom/' \
    --exclude 'diagnostic_dump.txt' --exclude 'DIAGNOSTIC_DUMP.md' --exclude 'LEAFLET_*.txt' \
    --exclude '*.png' --exclude '*.jpg' --exclude '*.jpeg' \
    "$MAIN_DIR/" "$TARGET_DIR/"
  # assets/ (logo) is needed by the dashboard; copy it explicitly
  if [ -d "$MAIN_DIR/assets" ]; then rsync -a --delete "$MAIN_DIR/assets/" "$TARGET_DIR/assets/"; fi
}

[ -d "$MAIN_DIR" ] || { echo "ERROR: main instance not found: $MAIN_DIR" >&2; exit 1; }
command -v rsync >/dev/null || { echo "ERROR: rsync is not installed (apt install rsync)" >&2; exit 1; }

# ── Update mode ─────────────────────────────────────────────────────────────
if [ "$UPDATE_CODE" -eq 1 ]; then
  [ -d "$TARGET_DIR" ] || { echo "ERROR: $TARGET_DIR does not exist" >&2; exit 1; }
  echo "Will sync code $MAIN_DIR -> $TARGET_DIR (data/ and .env are kept) and restart $UNIT."
  confirm "Continue?" || exit 1
  sync_code
  systemctl restart "$UNIT"
  sleep 3
  systemctl --no-pager --lines=5 status "$UNIT" || true
  exit 0
fi

# ── Create mode: preflight ──────────────────────────────────────────────────
[ -n "$ORG_NAME" ] && [ -n "$ORG_SLUG" ] && [ -n "$PORT" ] && [ "${#SECTORS[@]}" -gt 0 ] || {
  echo "ERROR: --org-name, --org-slug, --port and at least one --sector are required" >&2; exit 2; }
[ -e "$TARGET_DIR" ] && { echo "ERROR: $TARGET_DIR already exists. Not touching it." >&2; exit 1; }
[ -e "/etc/systemd/system/$UNIT" ] && { echo "ERROR: /etc/systemd/system/$UNIT already exists." >&2; exit 1; }
if ss -ltn "sport = :$PORT" | grep -q LISTEN; then
  echo "ERROR: port $PORT is already in use:" >&2; ss -ltnp "sport = :$PORT" >&2; exit 1
fi
[ -f "$MAIN_DIR/scripts/clone_sector_instance.py" ] || {
  echo "ERROR: $MAIN_DIR/scripts/clone_sector_instance.py missing. Deploy it to the main instance first." >&2; exit 1; }

MAIN_ENV="$(systemctl show -p EnvironmentFiles --value "$MAIN_UNIT" | awk '{print $1}')"
[ -n "$MAIN_ENV" ] || MAIN_ENV="$MAIN_DIR/.env"
[ -f "$MAIN_ENV" ] || { echo "ERROR: main .env not found ($MAIN_ENV)" >&2; exit 1; }

MAIN_EXEC="$(systemctl cat "$MAIN_UNIT" | grep -E '^ExecStart=' | tail -1)"
echo "Main unit: $MAIN_EXEC"
echo "$MAIN_EXEC" | grep -qE -- '--port[ =]8000' || {
  echo "ERROR: could not find '--port 8000' in $MAIN_UNIT ExecStart. Create the unit by hand (see docs/CLIENT_INSTANCES.md)." >&2; exit 1; }

if [ -n "$(git -C "$MAIN_DIR" status --porcelain 2>/dev/null)" ]; then
  echo "NOTE: main instance has uncommitted changes. The client instance gets the running code, which is what you want."
fi

PY="$(command -v python3)"
"$PY" -c "import multipart" 2>/dev/null || "$PY" -c "import python_multipart" 2>/dev/null || \
  echo "WARNING: python-multipart not importable by $PY (FastAPI file uploads). Main instance works, so check the interpreter in ExecStart."

echo
echo "Plan:"
echo "  new directory : $TARGET_DIR"
echo "  organization  : $ORG_NAME ($ORG_SLUG)"
echo "  sectors       : ${SECTORS[*]}"
echo "  employees in  : ${EMPLOYEES[*]:-none} (re-assigned to ${SECTORS[0]} in the copy)"
echo "  port          : $PORT"
echo "  systemd unit  : $UNIT (API only, no bot)"
confirm "Continue to dry run of the data copy?" || exit 1

SECTOR_ARGS=()
for s in "${SECTORS[@]}"; do SECTOR_ARGS+=(--sector "$s"); done
for e in "${EMPLOYEES[@]}"; do SECTOR_ARGS+=(--include-employee "$e"); done

# ── 1. Dry run of the data copy (writes nothing) ────────────────────────────
"$PY" "$MAIN_DIR/scripts/clone_sector_instance.py" --source-root "$MAIN_DIR" \
  --target-root "$TARGET_DIR" "${SECTOR_ARGS[@]}" --org-name "$ORG_NAME" --org-slug "$ORG_SLUG"
echo
confirm "Data report OK? Create $TARGET_DIR now?" || exit 1

# ── 2. Code ─────────────────────────────────────────────────────────────────
mkdir -p "$TARGET_DIR"
sync_code

# ── 3. Data ─────────────────────────────────────────────────────────────────
"$PY" "$MAIN_DIR/scripts/clone_sector_instance.py" --source-root "$MAIN_DIR" \
  --target-root "$TARGET_DIR" "${SECTOR_ARGS[@]}" --org-name "$ORG_NAME" --org-slug "$ORG_SLUG" --apply

# ── 4. .env ─────────────────────────────────────────────────────────────────
get_main() { grep -E "^$1=" "$MAIN_ENV" | tail -1 | cut -d= -f2- || true; }
DASH_USER="$ORG_SLUG"
DASH_PASS="$("$PY" -c 'import secrets;print(secrets.token_urlsafe(18))')"
INT_KEY="$("$PY" -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())' 2>/dev/null || true)"

umask 077
cat > "$TARGET_DIR/.env" <<EOF
# Forest AI client instance: $ORG_NAME
# Created $(date -u '+%Y-%m-%d %H:%M UTC') by deploy/create_client_instance.sh

DASHBOARD_USERNAME=$DASH_USER
DASHBOARD_PASSWORD=$DASH_PASS

# Shared with the main instance (same API accounts, costs are shared)
ANTHROPIC_API_KEY=$(get_main ANTHROPIC_API_KEY)
SENTINEL_CLIENT_ID=$(get_main SENTINEL_CLIENT_ID)
SENTINEL_CLIENT_SECRET=$(get_main SENTINEL_CLIENT_SECRET)
AI_OUTPUT_LANGUAGE=lv

# Own key: credentials stored in this instance are not readable by the main one
INTEGRATION_CREDENTIALS_KEY=$INT_KEY

# No Telegram bot for this instance yet (dashboard only). Sending messages from
# the dashboard will return an error until a separate bot token is set here
# and a forest-$SLUG-bot.service is created.
TELEGRAM_BOT_TOKEN=
DISPATCHER_CHAT_ID=
EOF
chmod 600 "$TARGET_DIR/.env"

# ── 5. systemd unit (derived from the main unit) ────────────────────────────
NEW_UNIT_TEXT="$(systemctl cat "$MAIN_UNIT" | grep -v '^#' \
  | sed -E "s#${MAIN_DIR}(/|\$| )#${TARGET_DIR}\1#g" \
  | sed -E "s#--port([ =])8000#--port\1${PORT}#" \
  | sed -E "s#^Description=.*#Description=Forest AI API — ${ORG_NAME} (client instance)#")"
if ! echo "$NEW_UNIT_TEXT" | grep -q "^WorkingDirectory=${TARGET_DIR}"; then
  NEW_UNIT_TEXT="$(echo "$NEW_UNIT_TEXT" | sed -E "s#^\[Service\]#[Service]\nWorkingDirectory=${TARGET_DIR}#")"
fi
if ! echo "$NEW_UNIT_TEXT" | grep -q "^EnvironmentFile=${TARGET_DIR}/.env"; then
  NEW_UNIT_TEXT="$(echo "$NEW_UNIT_TEXT" | grep -v '^EnvironmentFile=' | sed -E "s#^\[Service\]#[Service]\nEnvironmentFile=${TARGET_DIR}/.env#")"
fi
if echo "$NEW_UNIT_TEXT" | grep -qE "${MAIN_DIR}(/| |\$)"; then
  echo "ERROR: generated unit still references $MAIN_DIR. Create it by hand:" >&2; echo "$NEW_UNIT_TEXT" >&2; exit 1
fi

echo
echo "──────── /etc/systemd/system/$UNIT ────────"
echo "$NEW_UNIT_TEXT"
echo "────────────────────────────────────────────"
confirm "Install and start this unit?" || { echo "Stopped. $TARGET_DIR is ready; unit not installed."; exit 1; }
echo "$NEW_UNIT_TEXT" > "/etc/systemd/system/$UNIT"
systemctl daemon-reload
systemctl enable --now "$UNIT"

# ── 6. Firewall ─────────────────────────────────────────────────────────────
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  if ! ufw status | grep -qE "^$PORT(/tcp)?\s"; then
    confirm "ufw is active and port $PORT is closed. Open it (ufw allow $PORT/tcp)?" && ufw allow "$PORT/tcp"
  fi
fi

# ── 7. Health check ─────────────────────────────────────────────────────────
sleep 4
CODE="$(curl -s -o /dev/null -w '%{http_code}' -u "$DASH_USER:$DASH_PASS" "http://127.0.0.1:$PORT/api/sectors" || true)"
BAD="$(curl -s -o /dev/null -w '%{http_code}' -u "nobody:wrong" "http://127.0.0.1:$PORT/api/sectors" || true)"
echo
echo "Health: login -> $CODE (expect 200), wrong login -> $BAD (expect 401)"
systemctl --no-pager --lines=5 status "$UNIT" || true
echo
echo "════════════════════════════════════════════════════════"
echo " $ORG_NAME instance is ready"
echo "  URL      : http://$(hostname -I | awk '{print $1}'):$PORT"
echo "  login    : $DASH_USER"
echo "  password : $DASH_PASS   (stored only in $TARGET_DIR/.env)"
echo "  manifest : $TARGET_DIR/data/instance_manifest.json"
echo "════════════════════════════════════════════════════════"
