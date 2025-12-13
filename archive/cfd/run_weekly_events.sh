#!/usr/bin/env bash
# run_weekly_events.sh
# LaunchAgent wrapper to run weekly_events_update.py using the project's .venv.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$ROOT_DIR/.venv/bin/python3"
SCRIPT="$ROOT_DIR/weekly_events_update.py"

# Environment variables (edit if needed)
export LOCAL_GOOGLE_DRIVE="/Users/otomi/Google ドライブ"
# Do NOT place secrets here. Prefer Keychain (keyring) or an env var managed outside of files.
export OPENAI_API_KEY=""

LOG_OUT="/tmp/cfd3_autosystem.log"
LOG_ERR="/tmp/cfd3_autosystem.err"

mkdir -p "$(dirname "$LOG_OUT")"

exec >>"$LOG_OUT" 2>>"$LOG_ERR"
echo "==== RUN START: $(date -u +"%Y-%m-%d %H:%M:%S %Z") ===="
echo "ROOT_DIR=$ROOT_DIR"

if [[ -x "$VENV_PY" ]]; then
  echo "Using venv python: $VENV_PY"
  "$VENV_PY" "$SCRIPT" --file events.csv --service-account ~/.secrets/drive-sa.json
  rc=$?
else
  echo "No venv python found at $VENV_PY, falling back to system python3"
  python3 "$SCRIPT" --file events.csv --service-account ~/.secrets/drive-sa.json
  rc=$?
fi

echo "==== RUN END: $(date -u +"%Y-%m-%d %H:%M:%S %Z") (rc=$rc) ===="
exit $rc
