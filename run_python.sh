#!/usr/bin/env bash
# Convenience script to activate the project .venv and start an interactive Python session.
# Usage:
#   ./run_python.sh        # starts interactive python (or ipython if available)
#   ./run_python.sh --test # non-interactive test: prints which python will be used and version

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

if [[ "$1" == "--test" ]]; then
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    echo "Using venv python: $VENV_DIR/bin/python"
    "$VENV_DIR/bin/python" - <<'PY'
import sys
import platform
print('executable:', sys.executable)
print('version:', sys.version)
print('platform:', platform.platform())
PY
    exit 0
  else
    echo "No .venv found at $VENV_DIR. Falling back to system python3."
    python3 - <<'PY'
import sys
import platform
print('executable:', sys.executable)
print('version:', sys.version)
print('platform:', platform.platform())
PY
    exit 0
  fi
fi

if [[ -x "$VENV_DIR/bin/activate" || -x "$VENV_DIR/bin/python" ]]; then
  # Prefer ipython if installed in venv
  if [[ -x "$VENV_DIR/bin/ipython" ]]; then
    echo "Activating .venv and launching ipython..."
    exec "$VENV_DIR/bin/ipython"
  else
    echo "Activating .venv and launching python interactive shell..."
    exec "$VENV_DIR/bin/python" -i
  fi
else
  echo "No project .venv found at $VENV_DIR. You can create one with: python3 -m venv .venv"
  echo "Falling back to system python3 interactive shell..."
  exec python3 -i
fi
