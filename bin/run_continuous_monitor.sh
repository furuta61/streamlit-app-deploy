#!/usr/bin/env bash
# Wrapper to load runtime env (config/high_accuracy.env) then exec the monitor
set -euo pipefail

# Project root (this script is in bin/)
ROOT="/Users/otomi/Desktop/vs code/CFD3_AutoSystem"
cd "$ROOT"

# Load high accuracy env if present
if [ -f "$ROOT/config/high_accuracy.env" ]; then
  # shellcheck disable=SC1091
  source "$ROOT/config/high_accuracy.env"
fi

# Optionally load other env overrides
if [ -f "$ROOT/config/.env" ]; then
  # non-fatal
  # shellcheck disable=SC1091
  source "$ROOT/config/.env" || true
fi

# Exec the venv python with the monitor script so pid is the python process
exec "$ROOT/.venv/bin/python3" "$ROOT/continuous_monitor.py"
