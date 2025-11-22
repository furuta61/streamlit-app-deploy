#!/usr/bin/env python3
"""
hybrid_market_fetch.py
Hybrid fetcher that prefers Twelve Data but falls back to yfinance when
(1) Twelve has no data, or
(2) latest value differs from yfinance by >5% (abs diff / yf > 0.05).

Writes `market_data.csv` in the repository root (same as other scripts expect).
Outputs per-row `meta` JSON with keys: used ("twelve"|"yfinance"), mismatch_pct (float|null), twelve_source, twelve_interval, yf_candidate
"""
from pathlib import Path
import json
import pandas as pd
import numpy as np
import yfinance as yf
import logging
from logging.handlers import RotatingFileHandler

# import helpers from twelvedata_fetch
from twelvedata_fetch import get_api_key, fetch_symbol_series, ETF_FALLBACKS

OUT = Path(__file__).resolve().parent / 'market_data.csv'
LOG_DIR = Path(__file__).resolve().parent / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'hybrid_market_fetch.log'

# configure logging: detailed logs -> file (INFO), console -> WARNING to reduce noise
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    # file handler (rotating) keeps INFO+ logs for auditing
    fh = RotatingFileHandler(str(LOG_FILE), maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    # console: only warnings and above to avoid verbose Twelve Data messages flooding stdout
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.propagate = False

# Logical symbols to fetch (TOPIX intentionally excluded per user request)
SYMBOLS = ['JP225', 'NASDAQ', 'SP500', 'DE40', 'GOLD', 'AAPL', 'MSFT']

THRESHOLD = 0.05  # 5% mismatch threshold
# >>> PATCH START: per-symbol mismatch & stale detection <<<
MISMATCH_THRESH = {
    'GOLD': 0.02,
    'USDJPY': 0.02,
    'AAPL': 0.05,
    'MSFT': 0.05,
    'NASDAQ': 0.05,
    'SP500': 0.05,
    'JP225': 0.05,
    'DE40': 0.05,
}

def _business_days_ago(ts):
    """UTC naive timestampが今日から何営業日前かを返す（祝日考慮なし: 土日除外）"""
    import numpy as _np
    import pandas as _pd
    if ts is None or _pd.isna(ts):
        return None
    # ts を日付化
    d0 = _pd.Timestamp(ts).normalize().date()
    d1 = _pd.Timestamp.utcnow().normalize().date()
    try:
        return int(_np.busday_count(d0, d1))
    except Exception:
        # フォールバック（単純日数）
        return int((_pd.Timestamp.utcnow().normalize() - _pd.Timestamp(ts).normalize()).days)

def _augment_meta(meta_dict, last_dt):
    """meta に is_stale を付与して返す"""
    bd = _business_days_ago(last_dt)
    is_stale = (bd is not None and bd >= 3)
    meta2 = dict(meta_dict or {})
    meta2['is_stale'] = bool(is_stale)
    meta2['business_days_ago'] = int(bd) if bd is not None else None
    return meta2
# >>> PATCH END <<<


def latest_from_twelve(frame):
    if frame is None or frame.empty:
        return None
    df = frame.copy()
    if 'datetime' in df.columns:
        df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
        df = df.dropna(subset=['datetime'])
        df = df.sort_values('datetime')
        vals = pd.to_numeric(df['close'], errors='coerce').dropna()
        if vals.empty:
            return None
        return float(vals.iloc[-1])
    else:
        return None


def fetch_yf_candidate(cands, days=30, interval='1d'):
    """Try yfinance candidates in order and return (df, used_candidate) or (None, None)"""
    for c in cands:
        try:
            tk = yf.Ticker(c)
            # pick interval coarse for indices/ETFs
            hist = tk.history(period=f"{days}d", interval=interval)
            if hist is None or hist.empty:
                continue
            # pick Close or first numeric column
            if 'Close' in hist.columns:
                ser = hist['Close'].dropna()
            else:
                ser = None
                for col in hist.columns:
                    if pd.api.types.is_numeric_dtype(hist[col]):
                        ser = hist[col].dropna()
                        break
            if ser is None or ser.empty:
                continue
            df = pd.DataFrame({'date': ser.index, 'price': ser.values})
            df['date'] = pd.to_datetime(df['date'])
            df['source'] = 'yfinance'
            return df, c
        except Exception:
            continue
    return None, None


def main():
    api_key = None
    try:
        api_key = get_api_key()
        logger.info('Using Twelve API key from env/Keychain')
    except Exception as e:
        logger.warning('Twelve API key not found; will attempt yfinance-only fallback where needed')

    all_rows = []

    for sym in SYMBOLS:
        logger.info('Processing %s', sym)
        twelve_res = None
        try:
            if api_key:
                twelve_res = fetch_symbol_series(sym, api_key, days=30)
        except Exception as e:
            logger.exception('Twelve fetch error for %s: %s', sym, e)
            twelve_res = None

        tframe = None
        tsource = None
        tintv = None
        if twelve_res and isinstance(twelve_res, dict):
            tframe = twelve_res.get('frame')
            tsource = twelve_res.get('source')
            tintv = twelve_res.get('interval')

        t_latest = latest_from_twelve(tframe)

        # prepare yfinance candidates - prefer ETF_FALLBACKS if present
        yf_cands = ETF_FALLBACKS.get(sym, [sym])
        # try daily first, if symbol is intraday prefer 1h later (we use '1d' here)
        yf_df, used_cand = fetch_yf_candidate(yf_cands, days=60, interval='1d')
        y_latest = None
        if yf_df is not None and not yf_df.empty:
            y_latest = float(pd.to_numeric(yf_df['price'], errors='coerce').dropna().iloc[-1])

        chosen = None
        meta = {'used': None, 'mismatch_pct': None, 'twelve_source': tsource, 'twelve_interval': tintv, 'yf_candidate': used_cand}

        if t_latest is None and y_latest is None:
            logger.error('%s: neither twelve nor yfinance provided data', sym)
            continue
        elif t_latest is None:
            chosen = ('yfinance', yf_df)
            meta['used'] = 'yfinance'
            meta['mismatch_pct'] = None
            logger.info('  Twelve missing -> using yfinance %s', used_cand)
        elif y_latest is None:
            chosen = ('twelve', tframe.rename(columns={'datetime':'date','close':'price'}))
            meta['used'] = 'twelve'
            meta['mismatch_pct'] = None
            logger.info('  yfinance missing -> using twelve (source=%s)', tsource)
        else:
            # compute mismatch
            try:
                mismatch = abs(t_latest - y_latest) / (y_latest if y_latest != 0 else float('nan'))
            except Exception:
                mismatch = float('nan')
            meta['mismatch_pct'] = float(mismatch) if not np.isnan(mismatch) else None
            th = MISMATCH_THRESH.get(sym, THRESHOLD)
            if np.isnan(mismatch):
                chosen = ('yfinance', yf_df)
                meta['used'] = 'yfinance'
                logger.info('  mismatch unknown -> default to yfinance %s', used_cand)
            elif mismatch > th:
                chosen = ('yfinance', yf_df)
                meta['used'] = 'yfinance'
                logger.warning('  ⚠️ %s: mismatch %.3f (>%0.2f) -> yfinance %s', sym, mismatch, th, used_cand)
            else:
                chosen = ('twelve', tframe.rename(columns={'datetime':'date','close':'price'}))
                meta['used'] = 'twelve'
                logger.info('  %s: mismatch %.3f (≤%0.2f) -> use twelve', sym, mismatch, th)

        if chosen is None:
            continue
        src_name, df = chosen
        # normalize df
        if df is None or df.empty:
            continue
        df2 = df.copy()
        if 'date' in df2.columns:
            df2['date'] = pd.to_datetime(df2['date'], errors='coerce')
            # normalize timezone: convert tz-aware -> UTC then drop tzinfo; leave tz-naive as-is
            try:
                if df2['date'].dt.tz is not None:
                    df2['date'] = df2['date'].dt.tz_convert('UTC').dt.tz_localize(None)
            except Exception:
                # defensive fallback: coerce via string round-trip
                df2['date'] = pd.to_datetime(df2['date'].astype(str), errors='coerce')
        else:
            # try index
            df2 = df2.reset_index()
            df2['date'] = pd.to_datetime(df2['date'])
        if 'price' not in df2.columns:
            # attempt common names
            for c in ('close','Close'):
                if c in df2.columns:
                    df2 = df2.rename(columns={c:'price'})
                    break
        df2['price'] = pd.to_numeric(df2['price'], errors='coerce')
        # add symbol and meta
        # ここで最終行の時刻から is_stale を付与
        last_dt = None
        try:
            last_dt = pd.to_datetime(df2['date']).dropna().max()
        except Exception:
            last_dt = None

        meta = _augment_meta(meta, last_dt)
        meta_json = json.dumps(meta, ensure_ascii=False)

        df2['symbol'] = str(sym)
        df2['meta'] = meta_json
        # keep only date, price, symbol, meta
        all_rows.append(df2[['date','price','symbol','meta']])

    if not all_rows:
        logger.error('No data collected, aborting')
        return

    out = pd.concat(all_rows, ignore_index=True)
    # ensure date/symbol types are normalized before sorting
    out['date'] = pd.to_datetime(out['date'], errors='coerce')
    try:
        if out['date'].dt.tz is not None:
            out['date'] = out['date'].dt.tz_convert('UTC').dt.tz_localize(None)
    except Exception:
        out['date'] = pd.to_datetime(out['date'].astype(str), errors='coerce')
    out['symbol'] = out['symbol'].astype(str)
    out = out.sort_values(['symbol', 'date']).reset_index(drop=True)
    out.to_csv(OUT, index=False)
    logger.info('Saved hybrid market_data to %s', OUT)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        logger.exception('hybrid_market_fetch failed')
        raise
