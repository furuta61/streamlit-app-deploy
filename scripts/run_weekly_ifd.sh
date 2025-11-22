#!/usr/bin/env zsh
set -euo pipefail

# Wrapper to run weekly_events_update.py under project venv and capture logs.
REPO="/Users/otomi/Desktop/vs code/CFD3_AutoSystem"
cd "$REPO"

# Activate venv if present
if [ -f "$REPO/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$REPO/.venv/bin/activate"
fi

LOGDIR="$REPO/logs"
mkdir -p "$LOGDIR"
TS=$(date +"%Y%m%d_%H%M%S")
LOGFILE="$LOGDIR/weekly_run_${TS}.log"

echo "[$(date)] Starting weekly_events_update.py (strict)" >> "$LOGFILE"

# Adjust the --local-file path as needed (events list used to build IFD proposals)
"$REPO/.venv/bin/python3" "$REPO/weekly_events_update.py" --local-file "$REPO/scripts/events.csv" --out "$REPO/output" --strict >> "$LOGFILE" 2>&1
EXIT=$?

echo "[$(date)] Finished weekly_events_update.py exit=${EXIT}" >> "$LOGFILE"
exit $EXIT
