#!/bin/bash
# auto_run.sh - invoked by launchd
set -euo pipefail
set -euo pipefail
# auto_run.sh - invoked by launchd
# Uses the venv python binary directly to avoid environment differences under launchd

BASE="/Users/otomi/Desktop/CFD3_AutoSystem"
PY="$BASE/.venv/bin/python"
LOGOUT="$BASE/output/launchd.log"
LOGERR="$BASE/output/launchd_error.log"

mkdir -p "$BASE/output"
cd "$BASE"

echo "=== AUTO RUN START $(date -u +'%Y-%m-%dT%H:%M:%SZ') ===" >> "$LOGOUT" 2>>"$LOGERR"

# prefer to call the venv python directly; fallback to system python if not present
if [ -x "$PY" ]; then
  echo "Using venv python: $PY" >> "$LOGOUT"
else
  PY="/usr/bin/python3"
  echo "Venv python not found, fallback to: $PY" >> "$LOGOUT"
fi

"$PY" "$BASE/get_data.py"    >> "$LOGOUT" 2>>"$LOGERR" || echo "get_data.py failed" >> "$LOGERR"
"$PY" "$BASE/analyze_entry.py" >> "$LOGOUT" 2>>"$LOGERR" || echo "analyze_entry.py failed" >> "$LOGERR"
"$PY" "$BASE/generate_ifd.py"  >> "$LOGOUT" 2>>"$LOGERR" || echo "generate_ifd.py failed" >> "$LOGERR"

echo "=== AUTO RUN END $(date -u +'%Y-%m-%dT%H:%M:%SZ') ===" >> "$LOGOUT" 2>>"$LOGERR"

exit 0
