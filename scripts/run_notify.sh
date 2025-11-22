#!/usr/bin/env bash
set -euo pipefail

# Wrapper to run the notify_report in the project venv.
# It will source a .env file (if present) with environment variables.

ROOTDIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOTDIR"

ENVFILE="$ROOTDIR/.env"
if [ -f "$ENVFILE" ]; then
  # shellcheck disable=SC1090
  set -a
  # shellcheck source=/dev/null
  source "$ENVFILE"
  set +a
fi

exec "$ROOTDIR/.venv/bin/python3" -m app.notify_report
