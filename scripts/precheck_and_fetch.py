#!/usr/bin/env python3
"""Pre-check CSV freshness and attempt auto-fetch if stale.

Checks key CSVs in `data/` for recency before running scale/IFD pipeline.
If any required CSV is stale (older than CSV_MAX_AGE_HOURS), tries to invoke
`twelvedata_fetch.py` (or `market_data_fetch.py` fallback) to refresh data.

Usage: python3 scripts/precheck_and_fetch.py
Environment:
  CSV_MAX_AGE_HOURS (default 24)
  FETCH_COMMAND (optional) - command to run to refresh (overrides default)
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import subprocess
import logging
import pandas as pd
try:
    import market_data_tradingview as mdtv
except Exception:
    mdtv = None

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
LOG_FP = ROOT / 'output' / 'precheck_fetch.log'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# If set to any non-empty value, operate in TradingView-only mode (no external fetch fallbacks)
USE_TV_ONLY = bool(os.getenv('USE_TV_ONLY'))

# default files to check (symbol -> filename)
CHECK_FILES = {
    'XAUUSD': DATA_DIR / 'TVC_GOLD_240.csv',
    'NAS100': DATA_DIR / 'FOREXCOM_NAS100_240.csv',
    'JP225': DATA_DIR / 'FOREXCOM_JP225_240.csv',
}

def last_timestamp_from_csv(fp: Path) -> datetime | None:
    if not fp.exists():
        return None
    try:
        # read CSV without forcing date parsing (avoid crashes on malformed values)
        df = pd.read_csv(fp, index_col=False)
        if df.empty or 'time' not in df.columns:
            return None
        # coerce invalid time values to NaT rather than raising
        times = pd.to_datetime(df['time'], errors='coerce', utc=True)
        # drop invalid parsing results
        times = times.dropna()
        if times.empty:
            logging.warning('No valid time values parsed in %s', fp)
            return None
        # filter out implausible years to protect against corrupted rows
        # accept years roughly between 1970 and 2100
        times = times[(times.dt.year >= 1970) & (times.dt.year <= 2100)]
        if times.empty:
            logging.warning('All parsed time values are out-of-range in %s', fp)
            return None
        last = times.iloc[-1]
        return last.to_pydatetime().replace(tzinfo=timezone.utc)
    except Exception:
        logging.exception('Failed to parse CSV %s', fp)
        return None

def attempt_fetch():
    # allow user to override command
    cmd = os.environ.get('FETCH_COMMAND')
    if cmd:
        logging.info('Running custom fetch command: %s', cmd)
        rc = subprocess.call(cmd, shell=True)
        return rc == 0
    # Prefer TradingView (webhook or tradingview_ta) when available
    if mdtv is not None:
        logging.info('Attempting to refresh data using TradingView helpers')
        success_any = False
        for sym, fp in CHECK_FILES.items():
            try:
                # First try webhook latest price
                res = None
                try:
                    res = mdtv.fetch_price(sym)
                except Exception:
                    res = None
                if res and res.get('price') is not None:
                    price = float(res['price'])
                    # write a minimal CSV with time,open,high,low,close,volume using now as timestamp
                    now_iso = datetime.now(timezone.utc).isoformat()
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    with open(fp, 'w', encoding='utf-8') as fh:
                        fh.write('time,open,high,low,close,volume\n')
                        fh.write(f"{now_iso},{price},{price},{price},{price},0\n")
                    logging.info('Wrote TV webhook-derived CSV for %s -> %s', sym, fp)
                    success_any = True
                    continue

                # Fallback: try tradingview_ta screener auto if available
                try:
                    tvs = mdtv.get_tv_screener_data_auto(sym)
                except Exception:
                    tvs = None
                if tvs and tvs.get('price') is not None:
                    price = float(tvs['price'])
                    now_iso = datetime.now(timezone.utc).isoformat()
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    with open(fp, 'w', encoding='utf-8') as fh:
                        fh.write('time,open,high,low,close,volume\n')
                        fh.write(f"{now_iso},{price},{price},{price},{price},0\n")
                    logging.info('Wrote TV screener-derived CSV for %s -> %s', sym, fp)
                    success_any = True
                    continue
            except Exception:
                logging.exception('TradingView fetch attempt failed for %s', sym)
        if success_any:
            return True

    # If operator requested TV-only, do not attempt external fetch fallbacks
    if USE_TV_ONLY:
        logging.info('USE_TV_ONLY set: skipping external fetch fallbacks and relying on TradingView only')
        return False

    # default: try twelvedata_fetch.py then market_data_fetch.py
    td = ROOT / 'twelvedata_fetch.py'
    mdf = ROOT / 'market_data_fetch.py'
    if td.exists():
        logging.info('Attempting to refresh data using twelvedata_fetch.py')
        rc = subprocess.call(f'python3 "{td}"', shell=True)
        if rc == 0:
            return True
    if mdf.exists():
        logging.info('Attempting to refresh data using market_data_fetch.py')
        rc = subprocess.call(f'python3 "{mdf}"', shell=True)
        return rc == 0
    logging.error('No fetch script found (twelvedata_fetch.py or market_data_fetch.py)')
    return False

def main():
    max_age_h = float(os.environ.get('CSV_MAX_AGE_HOURS', '24'))
    now = datetime.now(timezone.utc)
    stale = []
    for sym, fp in CHECK_FILES.items():
        ts = last_timestamp_from_csv(fp)
        if ts is None:
            logging.warning('CSV for %s missing or unreadable: %s', sym, fp)
            stale.append((sym, fp, None))
            continue
        age = now - ts
        logging.info('CSV %s last timestamp %s (age %s)', fp.name, ts.isoformat(), age)
        if age > timedelta(hours=max_age_h):
            stale.append((sym, fp, ts))

    if not stale:
        logging.info('All CSVs fresh (within %dh)', max_age_h)
        return 0

    logging.info('Found stale or missing CSVs: %s', [s[0] for s in stale])
    ok = attempt_fetch()
    if not ok:
        logging.error('Auto-fetch failed; aborting pipeline to avoid applying bad scales')
        # log to output file for operator visibility
        try:
            LOG_FP.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FP, 'a', encoding='utf-8') as lf:
                lf.write(f"{datetime.now(timezone.utc).isoformat()}Z\tAUTO_FETCH_FAILED\t{[s[0] for s in stale]}\n")
        except Exception:
            pass
        return 2

    # after successful fetch, re-check
    still_stale = []
    for sym, fp, _ in stale:
        ts = last_timestamp_from_csv(fp)
        if ts is None or (now - ts) > timedelta(hours=max_age_h):
            still_stale.append(sym)
    if still_stale:
        logging.error('After fetch, these remain stale: %s', still_stale)
        return 3
    logging.info('Fetch succeeded and CSVs are now fresh')
    return 0

if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
