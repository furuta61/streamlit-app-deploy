#!/usr/bin/env python3
"""Wrapper runner for CFD3 AutoSystem monitoring.

Runs `weekly_events_update.py` and then `post_run_automation.py` when the
current local time is within the configured monitoring window. Designed to be
invoked frequently by launchd (e.g. every 5 minutes). The wrapper itself
decides whether to run (so launchd can run continuously while the wrapper
enforces the time window).

Monitoring window: 07:00 (inclusive) through 00:45 (next day, inclusive).
"""
from __future__ import annotations
import sys
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / '.venv' / 'bin' / 'python3'
WEEKLY = ROOT / 'weekly_events_update.py'
POST = ROOT / 'post_run_automation.py'
LOGS = ROOT / 'logs'


def minutes_since_midnight(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def in_monitor_window(now: datetime | None = None) -> bool:
    if now is None:
        now = datetime.now()
    t = minutes_since_midnight(now)
    start = 7 * 60           # 07:00
    end = 0 * 60 + 45        # 00:45 (next day) -> wrap-around
    # If window does not wrap midnight
    if start <= end:
        return start <= t <= end
    # Wrap-around (typical here: start > end)
    return t >= start or t <= end


def run_command(cmd, timeout=900):
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
        print(p.stdout)
        if p.stderr:
            print(p.stderr, file=sys.stderr)
        return p.returncode
    except Exception as e:
        print('Exception when running', cmd, e, file=sys.stderr)
        return 2


def find_latest_internal_csv() -> Path | None:
    files = sorted(LOGS.glob('events_scored_*_internal.csv'), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def main():
    if not in_monitor_window():
        print('Outside monitoring window — nothing to do.')
        return 0

    # Run the analysis/generation (no --dry-run)
    if not VENV_PY.exists():
        print('Python executable not found, using system python3')
        py = 'python3'
    else:
        py = str(VENV_PY)

    rc = run_command([py, str(WEEKLY)])
    if rc != 0:
        print('weekly_events_update.py returned', rc)

    latest = find_latest_internal_csv()
    if not latest:
        print('No internal CSV found after run — nothing to post-process')
        return 0

    # Call post_run_automation to copy/sync and notify
    rc2 = run_command([py, str(POST), '--file', str(latest)], timeout=600)
    if rc2 != 0:
        print('post_run_automation.py returned', rc2)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
