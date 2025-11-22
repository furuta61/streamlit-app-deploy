#!/usr/bin/env python3
"""
realtime_ifd_run.py
- Fetch latest market data (past 1 day) and save to market_data.csv
- Run weekly_events_update.py to generate IFDs from local events.csv
- Print summary table from the newest internal CSV

One-click usage (no args):
    ./.venv/bin/python3 realtime_ifd_run.py
"""
import sys
import os
from pathlib import Path
import subprocess
import glob
import time
import pandas as pd

ROOT = Path(__file__).resolve().parent
MARKET_DATA_PATH = ROOT / 'market_data.csv'
LOGS_DIR = ROOT / 'logs'
# GMOデイトレ用スクリプトに変更（リアルタイムトレンド分析付き）
WEEKLY_SCRIPT = ROOT / 'cfd3_ifd_daytrade.py'
EVENTS_FILE = ROOT / 'events.csv'

print("🚀 Realtime IFD Run Started")

# 1) Fetch market data (past 1 day)
try:
    # import the existing function from market_data_fetch if available
    from market_data_fetch import fetch_market_data, save_market_data
    df = fetch_market_data(days=1, interval='1h', use_cache=False)
    try:
        save_market_data(df, str(MARKET_DATA_PATH))
    except Exception:
        # fallback to writing csv directly
        df.to_csv(MARKET_DATA_PATH, index=False, encoding='utf-8-sig')
    print(f"✅ Market data updated: {MARKET_DATA_PATH}")
except Exception as e:
    print("⚠️ Failed to fetch market data:", e)
    # continue; weekly script may still run using existing cache

# small pause so file timestamps order is stable
time.sleep(0.5)

# 2) Call cfd3_ifd_daytrade.py（リアルタイムトレンド分析）
if not WEEKLY_SCRIPT.exists():
    print(f"❌ cfd3_ifd_daytrade.py not found: {WEEKLY_SCRIPT}")
    sys.exit(1)

# Use same Python interpreter
cmd = [sys.executable, str(WEEKLY_SCRIPT)]
print('· Executing cfd3_ifd_daytrade.py with realtime trend analysis...')
try:
    proc = subprocess.run(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    # print stdout/stderr to console for immediate feedback
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.returncode != 0:
        print(f"⚠️ cfd3_ifd_daytrade.py exited with code {proc.returncode}")
    else:
        print("✅ リアルタイムトレンド分析＆IFD生成完了")
except Exception as e:
    print("❌ Failed to execute cfd3_ifd_daytrade.py:", e)
    sys.exit(1)

# 3) find newest internal CSV and display key columns
try:
    pattern = str(LOGS_DIR / 'events_scored_*_internal.csv')
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    if not files:
        print('⚠️ No internal events_scored CSV found in logs directory:', LOGS_DIR)
    else:
        latest = files[-1]
        df = pd.read_csv(latest)
        cols = ['signal', 'entry_source', 'entry', 'TP', 'SL', 'lot_size', 'risk_amount']
        present = [c for c in cols if c in df.columns]
        try:
            from tabulate import tabulate
            print('\n📋 Latest IFD (from: {})'.format(latest))
            print(tabulate(df[present], headers=present, tablefmt='github', showindex=False))
        except Exception:
            print('\n📋 Latest IFD (pandas preview):')
            print(df[present].head(20).to_string(index=False))

except Exception as e:
    print('⚠️ Failed to read latest internal CSV:', e)

print('\n🏁 Realtime IFD completed successfully')
