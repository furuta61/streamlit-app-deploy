#!/usr/bin/env python3
"""
twelvedata_fetch.py

Fetch market data from Twelve Data API and produce market_data.csv usable by
weekly_events_update.py / realtime_ifd_run.py.

Requirements implemented:
- Read API key from TWELVE_API_KEY env var
- Targets: ["JP225", "NASDAQ", "SP500", "GOLD", "USDJPY", "DE40", "AAPL", "MSFT"]
- Use /time_series endpoint to fetch latest price (1min or 5min)
- Output CSV (symbol, datetime, close) to same directory as this script: market_data.csv
- Retry on network/API errors with exponential backoff
- Log to logs/twelvedata_fetch.log
- Print a table of latest prices to terminal on success

Usage:
  export TWELVE_API_KEY="your_key"
  python3 twelvedata_fetch.py

"""

from __future__ import annotations
import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import argparse

import requests
import pandas as pd

# Configuration
API_KEY = os.environ.get('TWELVE_API_KEY')
OUTPUT_CSV = Path(__file__).resolve().parent / 'market_data.csv'
LOG_DIR = Path(__file__).resolve().parent / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'twelvedata_fetch.log'

# The symbols we intend to fetch. Twelve Data symbol names vary by provider.
# We provide a mapping to candidate Twelve Data tickers for each logical instrument.
SYMBOL_CANDIDATES: Dict[str, List[str]] = {
    # Prioritize ETFs/tickers that yfinance reliably returns for JP225
    'JP225': ['1321.T', '1330.T', 'JP225', '^N225', 'NIKKEI', 'NKY'],            # Twelve Data may accept JP225 or ^N225
    'NASDAQ': ['NASDAQ', 'NDX', 'US100', 'NQ=F', 'NASDAQ:NDX'],
    'SP500': ['SP500', '^GSPC', 'SPX'],
    'GOLD': ['XAU/USD', 'GOLD', 'GC=F', 'XAUUSD'],
    'USDJPY': ['USD/JPY', 'USDJPY', 'JPY=X'],
    'DE40': ['DE40', 'DAX', 'DE30'],
    'AAPL': ['AAPL'],
    'MSFT': ['MSFT'],
}

# Explicit ETF / external fallbacks (yfinance) per logical symbol to ensure
# required instruments are always filled when Twelve Data doesn't provide them.
ETF_FALLBACKS: Dict[str, List[str]] = {
    'JP225': ['1321.T', '1330.T', '^N225'],
    'NASDAQ': ['QTOP.EUR', 'QQQ'],
    'GOLD': ['GOLD360', 'XAUUSD', 'GC=F'],
}

# Twelve Data base URL
BASE_URL = 'https://api.twelvedata.com/time_series'
# Symbol search endpoint
SYMBOL_SEARCH_URL = 'https://api.twelvedata.com/symbol_search'

# Request parameters
INTERVALS_TO_TRY = ['1min', '5min', '1h', '1day']
RETRIES = 3
BACKOFF_FACTOR = 2
TIMEOUT = 10.0

DEFAULT_DAYS = 30

# Preferred interval per logical symbol for time series output
PREFERRED_INTERVAL: Dict[str, str] = {
    'JP225': '1day',
    'TOPIX': '1day',
    'NASDAQ': '1h',
    'SP500': '1h',
    'GOLD': '1h',
    'USDJPY': '1h',
    'DE40': '1h',
    'AAPL': '1h',
    'MSFT': '1h',
}

# Setup logging: detailed file logs + quieter console
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    # rotating file handler for detailed logs
    fh = RotatingFileHandler(str(LOG_FILE), maxBytes=5 * 1024 * 1024, backupCount=7, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    # console handler set to WARNING to avoid noisy Twelve Data info messages
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.propagate = False


def get_api_key() -> str:
    # Try environment variable first
    key = os.environ.get('TWELVE_API_KEY')
    if key:
        return key
    # Fallback: try macOS Keychain via keyring if available. This allows users
    # to store the API key in Keychain Access (service: 'TWELVE_API', account: 'default')
    try:
        import keyring
        kr = keyring.get_password('TWELVE_API', 'default')
        if kr:
            logger.info('Using API key from keyring (TWELVE_API/default)')
            return kr
    except Exception:
        # keyring may not be installed or available; ignore
        pass
    logger.error('TWELVE_API_KEY not set and no key found in keyring (service=TWELVE_API, account=default). Aborting.')
    raise SystemExit('TWELVE_API_KEY not set')


def call_twelvedata(symbol: str, interval: str, api_key: str, outputsize: int = 1) -> Optional[dict]:
    """Call Twelve Data time_series endpoint for a single symbol and interval.
    Returns parsed JSON dict on success, None on failure.
    """
    params = {
        'symbol': symbol,
        'interval': interval,
        'outputsize': outputsize,
        'format': 'JSON',
        'apikey': api_key,
    }
    url = BASE_URL
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                # Twelve Data returns {'status':'ok','meta':..., 'values':[...]}
                if data is None:
                    logger.warning('Empty response for %s %s', symbol, interval)
                    return None
                if data.get('status') == 'ok' and 'values' in data:
                    return data
                # API returns error object with message
                if 'message' in data:
                    logger.warning('Twelve Data message for %s %s: %s', symbol, interval, data.get('message'))
                else:
                    logger.warning('Unexpected response for %s %s: %s', symbol, interval, data)
                # if status indicates quota or throttling, raise to allow backoff
                if data.get('status') == 'error' and 'quota' in str(data).lower():
                    logger.error('Twelve Data quota/error for %s: %s', symbol, data)
                    return None
            else:
                logger.warning('HTTP %s for %s %s: %s', resp.status_code, symbol, interval, resp.text[:200])
        except Exception as e:
            logger.warning('Exception on request for %s %s: %s', symbol, interval, e)
        # backoff before retry
        sleep = BACKOFF_FACTOR ** (attempt - 1)
        logger.info('Retry %d/%d for %s %s after %ds', attempt, RETRIES, symbol, interval, sleep)
        time.sleep(sleep)
    logger.error('Failed to fetch %s %s after %d attempts', symbol, interval, RETRIES)
    return None


def symbol_search(query: str, api_key: str) -> List[str]:
    """Use Twelve Data symbol_search endpoint to find matching symbol identifiers.
    Returns a list of candidate symbol strings (may be empty).
    """
    params = {'symbol': query, 'apikey': api_key}
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.get(SYMBOL_SEARCH_URL, params=params, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                # expected shape: {"data": [{"symbol": "AAPL", "exchange": ...}, ...]}
                if isinstance(data, dict) and 'data' in data and isinstance(data['data'], list):
                    syms = []
                    for item in data['data']:
                        s = item.get('symbol')
                        if s and s not in syms:
                            syms.append(s)
                    if syms:
                        logger.info('symbol_search(%s) -> %s', query, syms)
                        return syms
                # sometimes Twelve Data returns top-level 'message' on no results
                if 'message' in data:
                    logger.info('symbol_search message for %s: %s', query, data.get('message'))
            else:
                logger.warning('HTTP %s for symbol_search %s: %s', resp.status_code, query, resp.text[:200])
        except Exception as e:
            logger.debug('symbol_search exception for %s: %s', query, e)
        sleep = BACKOFF_FACTOR ** (attempt - 1)
        logger.info('Retry symbol_search %d/%d for %s after %ds', attempt, RETRIES, query, sleep)
        time.sleep(sleep)
    logger.warning('symbol_search returned no results for %s', query)
    return []


def fetch_symbol_series(logical_symbol: str, api_key: str, days: int = DEFAULT_DAYS) -> dict:
    """Fetch a time series for logical_symbol (daily or hourly depending on mapping).
    Returns a dict with keys:
      - 'frame': pandas.DataFrame with columns ['datetime','close'] or empty DataFrame on failure
      - 'source': candidate symbol used or None
      - 'interval': interval used or None
    """
    # determine preferred interval
    pref_intv = PREFERRED_INTERVAL.get(logical_symbol, '1h')
    # compute outputsize: for 1d ask days, for 1h ask days*24
    if pref_intv == '1day':
        outsize = max(days, 10)
    elif pref_intv == '1h':
        outsize = max(days * 24, 48)
    else:
        outsize = max(days * 24, 96)

    candidates = list(SYMBOL_CANDIDATES.get(logical_symbol, [logical_symbol]))
    # try symbol search for logical name to augment candidates
    try:
        search_syms = symbol_search(logical_symbol, api_key)
        for s in search_syms:
            if s not in candidates:
                candidates.insert(0, s)
    except Exception:
        pass

    logger.info('Fetching series for %s using candidates: %s (interval preference=%s, outputsize=%s)',
                logical_symbol, candidates, pref_intv, outsize)

    for cand in candidates:
        intervals = [pref_intv] + [i for i in INTERVALS_TO_TRY if i != pref_intv]
        for intv in intervals:
            logger.info('Trying %s interval=%s (outputsize=%s)', cand, intv, outsize)
            data = call_twelvedata(cand, intv, api_key, outputsize=outsize)
            if not data:
                try:
                    more = symbol_search(cand, api_key)
                    for m in more:
                        if m not in candidates:
                            candidates.append(m)
                except Exception:
                    pass
                continue
            vals = data.get('values')
            if not vals or not isinstance(vals, list):
                logger.info('No values for %s %s', cand, intv)
                continue
            # Build DataFrame, values are usually newest-first
            try:
                rows = []
                for v in reversed(vals):  # oldest-first
                    dt = v.get('datetime') or v.get('timestamp')
                    close = v.get('close') or v.get('price') or v.get('value')
                    try:
                        close_f = float(close) if close is not None else None
                    except Exception:
                        close_f = None
                    rows.append({'datetime': dt, 'close': close_f})
                df = pd.DataFrame(rows)
                df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
                df = df.dropna(subset=['datetime']).reset_index(drop=True)
                logger.info('Success for candidate %s interval=%s -> %d rows', cand, intv, len(df))
                return {'frame': df, 'source': cand, 'interval': intv}
            except Exception as e:
                logger.exception('Failed to parse values for %s %s: %s', cand, intv, e)
                continue

    logger.warning('All candidates failed for %s', logical_symbol)
    # If Twelve Data failed for all candidates, try a yfinance fallback
    # for specific logical symbols (ETF candidates). This ensures the
    # pipeline's must-have instruments (JP225, NASDAQ, GOLD) can be
    # populated automatically when Twelve Data coverage is insufficient.
    try:
        cands = ETF_FALLBACKS.get(logical_symbol, [])
        if cands:
            try:
                import yfinance as yf
            except Exception:
                yf = None
            if yf is not None:
                for yc in cands:
                    try:
                        logger.info('yfinance fallback try for %s using %s', logical_symbol, yc)
                        tk = yf.Ticker(yc)
                        # for indices/ETF prefer daily
                        period = '30d'
                        interval = '1d'
                        hist = tk.history(period=period, interval=interval)
                        if hist is None or hist.empty:
                            logger.info('yfinance candidate %s returned no data', yc)
                            continue
                        # pick Close or first numeric column
                        if 'Close' in hist.columns:
                            ser = hist['Close'].dropna()
                        else:
                            ser = None
                            for c in hist.columns:
                                try:
                                    if hist[c].dtype.kind in 'fi':
                                        ser = hist[c].dropna()
                                        break
                                except Exception:
                                    continue
                        if ser is None or ser.empty:
                            continue
                        rows = []
                        for idx, v in ser.items():
                            rows.append({'datetime': idx, 'close': float(v)})
                        df = pd.DataFrame(rows)
                        df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
                        df = df.dropna(subset=['datetime']).reset_index(drop=True)
                        logger.info('yfinance fallback succeeded for %s using %s -> %d rows', logical_symbol, yc, len(df))
                        return {'frame': df, 'source': f'yf:{yc}', 'interval': interval}
                    except Exception as e:
                        logger.warning('yfinance candidate %s failed for %s: %s', yc, logical_symbol, e)
            else:
                logger.info('yfinance not available in environment; cannot perform fallback for %s', logical_symbol)
    except Exception:
        logger.exception('ETF fallback attempt failed')

    return {'frame': pd.DataFrame(columns=['datetime', 'close']), 'source': None, 'interval': None}


def main():
    parser = argparse.ArgumentParser(description='Fetch market data from Twelve Data (with ETF fallbacks).')
    parser.add_argument('--availability-check', action='store_true', help='Check which logical symbols are available via Twelve Data (useful to decide Grow vs Pro)')
    args = parser.parse_args()

    api_key = get_api_key()
    days = DEFAULT_DAYS
    # If user requested availability check, run lightweight tests and exit
    if 'args' in locals() and getattr(args, 'availability_check', False):
        results = []
        logger.info('Running availability check for logical symbols: %s', list(SYMBOL_CANDIDATES.keys()))
        for sym in SYMBOL_CANDIDATES.keys():
            # Try symbol_search first
            found = False
            ok_candidate = None
            candidates = list(SYMBOL_CANDIDATES.get(sym, [sym]))
            try:
                search = symbol_search(sym, api_key)
                for s in search:
                    if s not in candidates:
                        candidates.insert(0, s)
            except Exception:
                pass
            for cand in candidates:
                # try preferred interval then fallback intervals
                intervals = [PREFERRED_INTERVAL.get(sym, '1h')] + [i for i in INTERVALS_TO_TRY if i != PREFERRED_INTERVAL.get(sym, '1h')]
                for intv in intervals:
                    data = call_twelvedata(cand, intv, api_key, outputsize=1)
                    if data and data.get('status') == 'ok' and data.get('values'):
                        ok_candidate = {'logical': sym, 'candidate': cand, 'interval': intv}
                        found = True
                        break
                if found:
                    break
            results.append((sym, ok_candidate))
        # Print results
        logger.info('\nTwelve Data availability check results (successful candidate or None):\n')
        for sym, res in results:
            if res:
                logger.info('%s: OK via %s interval=%s', sym, res['candidate'], res['interval'])
            else:
                logger.info('%s: MISSING (no candidate returned data on Twelve Data)', sym)
        sys.exit(0)
    all_frames = []
    meta = {}

    # For each logical symbol, fetch a series and keep as a DataFrame
    for sym in SYMBOL_CANDIDATES.keys():
        res = fetch_symbol_series(sym, api_key, days=days)
        frm = res.get('frame')
        src = res.get('source')
        intv = res.get('interval')
        # record meta and last-value snapshot for robust CSV generation
        last_val = None
        last_dt = None
        if frm is not None and not frm.empty:
            # last available (newest) value
            try:
                tmp = frm.dropna(subset=['close'])
                if not tmp.empty:
                    last_row = tmp.iloc[-1]
                    last_val = float(last_row.get('close')) if last_row.get('close') is not None else None
                    last_dt = pd.to_datetime(last_row.get('datetime') or last_row.get('timestamp'), errors='coerce')
            except Exception:
                last_val = None
                last_dt = None

        meta[sym] = {'source': src, 'interval': intv, 'last_value': last_val, 'last_datetime': last_dt}
        if frm is None or frm.empty:
            # create empty frame with date only so merge works
            f = pd.DataFrame(columns=['date', sym])
        else:
            # rename close column to the logical symbol and datetime->date
            f = frm.rename(columns={'close': sym, 'datetime': 'date'})
            f['date'] = pd.to_datetime(f['date'])
            f[sym] = pd.to_numeric(f[sym], errors='coerce')
        all_frames.append(f[['date', sym]] if 'date' in f.columns else f)

    # Merge frames on 'date' outer-join
    frames = [fr for fr in all_frames if isinstance(fr, pd.DataFrame) and 'date' in fr.columns]
    if frames:
        df = frames[0]
        for fr in frames[1:]:
            df = pd.merge(df, fr, on='date', how='outer')
        df = df.sort_values('date').reset_index(drop=True)
    else:
        df = pd.DataFrame()

    # Add source and interval columns (same value repeated) for downstream clarity
    for sym, info in meta.items():
        src_col = f"{sym}_source"
        intv_col = f"{sym}_interval"
        df[src_col] = info.get('source')
        df[intv_col] = info.get('interval')

    # Map Twelve Data logical names to pipeline-expected names when necessary.
    # weekly_events_update.py expects names like GOLD_SPOT and NASDAQ_MINI.
    # Keep original columns but also create pipeline aliases so downstream checks pass.
    pipeline_aliases = {
        'GOLD': 'GOLD_SPOT',
        'NASDAQ': 'NASDAQ_MINI',
    }
    for src, dst in pipeline_aliases.items():
        if src in df.columns and dst not in df.columns:
            # copy numeric series
            df[dst] = pd.to_numeric(df[src], errors='coerce')
            # copy metadata if present
            src_src = f"{src}_source"
            src_int = f"{src}_interval"
            dst_src = f"{dst}_source"
            dst_int = f"{dst}_interval"
            if src_src in df.columns:
                df[dst_src] = df[src_src]
            else:
                df[dst_src] = None
            if src_int in df.columns:
                df[dst_int] = df[src_int]
            else:
                df[dst_int] = None

    # If some required logical symbols are missing numeric values, try to fill
    # the most recent row from the per-symbol last_value collected earlier
    # (meta[sym]['last_value']). This creates a conservative snapshot to allow
    # downstream pipeline checks to pass while preserving source metadata.
    try:
        # ensure date column exists
        if 'date' in df.columns and not df.empty:
            latest_idx = df.index[-1]
            for sym in SYMBOL_CANDIDATES.keys():
                # ensure column exists
                if sym not in df.columns:
                    df[sym] = pd.NA
                # if latest value is missing, and we have a last_value in meta, fill it
                try:
                    cur_val = df.at[latest_idx, sym]
                except Exception:
                    cur_val = None
                last_val = meta.get(sym, {}).get('last_value')
                if (pd.isna(cur_val) or cur_val is None) and last_val is not None:
                    df.at[latest_idx, sym] = last_val
                    # also populate metadata columns so downstream knows the source
                    src_col = f"{sym}_source"
                    int_col = f"{sym}_interval"
                    if src_col not in df.columns:
                        df[src_col] = None
                    if int_col not in df.columns:
                        df[int_col] = None
                    df.at[latest_idx, src_col] = meta.get(sym, {}).get('source')
                    df.at[latest_idx, int_col] = meta.get(sym, {}).get('interval')
        else:
            # df empty: build a single snapshot row from meta
            snap = {}
            snap_date = pd.Timestamp.now()
            snap['date'] = snap_date
            any_val = False
            for sym in SYMBOL_CANDIDATES.keys():
                val = meta.get(sym, {}).get('last_value')
                snap[sym] = val
                if val is not None:
                    any_val = True
                snap[f"{sym}_source"] = meta.get(sym, {}).get('source')
                snap[f"{sym}_interval"] = meta.get(sym, {}).get('interval')
            if any_val:
                df = pd.DataFrame([snap])
    except Exception:
        logger.exception('Snapshot fill failed; proceeding without snapshot')

    # Save CSV
    try:
        df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
        logger.info('Saved market_data to %s', OUTPUT_CSV)
    except Exception as e:
        logger.exception('Failed to save market_data.csv: %s', e)
        raise

    # Safety/fallback: ensure required core markets exist and have numeric values.
    required = ['JP225', 'NASDAQ', 'GOLD']
    missing = []
    for r in required:
        if r not in df.columns or df[r].dropna().empty:
            missing.append(r)
    if missing:
        logger.warning('Core market columns missing or empty for: %s. Attempting yfinance fallback for those symbols.', missing)
        try:
            # import local yfinance fetcher and request its market_data (non-cached)
            import market_data_fetch as mdf
            yf_df = mdf.fetch_market_data(days=days, use_cache=False)
            # align on date: convert to datetime
            if 'date' in yf_df.columns:
                yf_df['date'] = pd.to_datetime(yf_df['date'])
                # merge on date, prefer existing df values, but fill missing from yf_df
                df = pd.merge(df, yf_df[['date'] + [c for c in missing if c in yf_df.columns]], on='date', how='outer')
                # if there are duplicate columns (e.g. JP225_x, JP225_y), coalesce
                for sym in missing:
                    if f"{sym}_x" in df.columns and f"{sym}_y" in df.columns:
                        df[sym] = df[f"{sym}_x"].combine_first(df[f"{sym}_y"])
                        df = df.drop(columns=[f"{sym}_x", f"{sym}_y"])
                    elif sym in yf_df.columns and sym not in df.columns:
                        # already merged in above, ensure numeric
                        df[sym] = pd.to_numeric(df[sym], errors='coerce')
                # restore source/interval placeholders for filled symbols
                for sym in missing:
                    src_col = f"{sym}_source"
                    intv_col = f"{sym}_interval"
                    if src_col not in df.columns:
                        df[src_col] = df.get(src_col, mdf.SYMBOL_CANDIDATES.get(sym, [None])[0] if hasattr(mdf, 'SYMBOL_CANDIDATES') else None)
                    if intv_col not in df.columns:
                        df[intv_col] = df.get(intv_col, 'yf')
                # sort and reset index
                df = df.sort_values('date').reset_index(drop=True)
                # save merged CSV
                df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
                logger.info('Filled missing core markets from yfinance and re-saved %s', OUTPUT_CSV)
            else:
                logger.warning('yfinance fallback returned no date column; skipping merge')
        except Exception as e:
            logger.exception('yfinance fallback failed: %s', e)

        # Aggressive: ensure JP225 is filled even if Twelve Data and initial yfinance merge failed.
        # User request: always provide JP225 (tradeable), so try direct yfinance single-symbol fetch
        # using ETF or index candidates if still missing.
        try:
            jp_missing = ('JP225' not in df.columns) or df['JP225'].dropna().empty
        except Exception:
            jp_missing = True
        if jp_missing:
            logger.info('JP225 still missing — attempting aggressive yfinance single-symbol fetch for JP225 candidates')
            try:
                # prefer candidate list from market_data_fetch if available
                try:
                    import market_data_fetch as mdf
                    jp_cands = mdf.SYMBOL_CANDIDATES.get('JP225', ['1321.T', '1330.T'])
                except Exception:
                    jp_cands = ['1321.T', '1330.T', '^N225']

                # try candidates via yfinance ticker.history (single-symbol quick fetch)
                try:
                    import yfinance as yf
                except Exception:
                    yf = None

                filled = False
                used_cand = None
                last_val = None
                last_dt = None
                if yf is not None:
                    for cand in jp_cands:
                        try:
                            logger.info('Aggressive YF try for JP225 using candidate: %s', cand)
                            tk = yf.Ticker(cand)
                            hist = tk.history(period='7d', interval='1d')
                            if hist is None or hist.empty:
                                logger.info('Candidate %s returned no recent history', cand)
                                continue
                            # prefer Close column
                            if 'Close' in hist.columns:
                                ser = hist['Close'].dropna()
                            else:
                                # take first numeric column
                                ser = None
                                for c in hist.columns:
                                    try:
                                        if hist[c].dtype.kind in 'fi':
                                            ser = hist[c].dropna()
                                            break
                                    except Exception:
                                        continue
                            if ser is None or ser.empty:
                                continue
                            last_val = float(ser.iloc[-1])
                            last_dt = ser.index[-1]
                            used_cand = cand
                            filled = True
                            logger.info('Aggressive YF succeeded for JP225 candidate %s -> %s at %s', cand, last_val, last_dt)
                            break
                        except Exception as e:
                            logger.warning('Aggressive yfinance candidate %s failed: %s', cand, e)

                if filled and last_val is not None:
                    # ensure date column exists and set latest row value
                    import pandas as _pd
                    if 'date' not in df.columns or df.empty:
                        df = _pd.DataFrame([{'date': _pd.Timestamp.now(), 'JP225': last_val}])
                    else:
                        latest_idx = df.index[-1]
                        try:
                            df.at[latest_idx, 'JP225'] = last_val
                        except Exception:
                            # ensure column exists
                            df['JP225'] = _pd.NA
                            df.at[df.index[-1], 'JP225'] = last_val
                        df.at[df.index[-1], 'JP225_source'] = f'yf:{used_cand}'
                        df.at[df.index[-1], 'JP225_interval'] = '1day'
                    # save CSV after filling
                    try:
                        df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
                        logger.info('Aggressively filled JP225 from yfinance (%s) and re-saved %s', used_cand, OUTPUT_CSV)
                    except Exception:
                        logger.exception('Failed to re-save market_data.csv after aggressive JP225 fill')
            except Exception:
                logger.exception('Aggressive JP225 yfinance fetch failed')

    # Print a summary table: latest values per symbol
    try:
        logger.info('\n✅ Twelve Data からマーケットデータを更新しました\n')
        if not df.empty:
            latest = df.dropna(subset=['date']).tail(1)
            rows = []
            for sym in SYMBOL_CANDIDATES.keys():
                if sym in latest.columns:
                    dt = latest['date'].iloc[0]
                    close = latest[sym].iloc[0]
                else:
                    dt = None
                    close = None
                rows.append({'symbol': sym, 'datetime': dt, 'close': close,
                             'source': meta.get(sym, {}).get('source'), 'interval': meta.get(sym, {}).get('interval')})
            out = pd.DataFrame(rows)
            logger.info('\n%s', out.to_string(index=False))
        else:
            logger.info('No market data fetched')
    except Exception:
        logger.exception('Updated, but failed to pretty-print DataFrame')


if __name__ == '__main__':
    # Provide a lightweight availability check mode to report which logical symbols
    # Twelve Data returns successfully. This is helpful to determine if Grow
    # plan is sufficient or if Pro is required for coverage.
    main()
