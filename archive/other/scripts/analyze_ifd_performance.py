#!/usr/bin/env python3
"""
analyze_ifd_performance.py

Simple analysis tool for `output/ifd_orders.jsonl` (NDJSON) or a provided JSON/CSV file.
Supports downloading a public Google Drive link via gdown (if available). Computes:
 - counts per decision
 - rating distributions
 - forward returns at 1h/6h/24h using yfinance (where possible)
 - correlation of rating and RSI with forward returns
 - produces CSV summary and a Markdown report with basic stats

Usage:
  python3 scripts/analyze_ifd_performance.py --input output/ifd_orders.jsonl --outdir output/analysis_20251106

If --input is a Google Drive share URL, the script will try to use `gdown` to download it.

"""

import os
import sys
import json
import argparse
import tempfile
import datetime as dt
from collections import defaultdict

try:
    import pandas as pd
    import numpy as np
    import yfinance as yf
    import matplotlib.pyplot as plt
except Exception as e:
    print("Required packages missing. Ensure pandas, numpy, yfinance and matplotlib are installed.")
    raise

# mapping from system symbols to Yahoo tickers for forward-return lookup
YF_SYMBOL_MAP = {
    'JP225': '^N225',
    'NQ100': '^NDX',
    'GER40': '^GDAXI',
    'XAUUSD': 'GC=F',
    'XAGUSD': 'SI=F',
    'NGAS': 'NG=F',
}

FORWARD_HOURS = [1, 6, 24]
# maximum allowed difference (in seconds) between event ts and nearest hourly index
NEAREST_THRESHOLD_SECONDS = 2 * 3600  # 2 hours


def download_if_needed(path_or_url: str) -> str:
    """
    If path_or_url looks like a URL, try to download it to a temp file and return path.
    Supports local paths (returned as-is) and public Google Drive links using gdown if installed.
    """
    if os.path.exists(path_or_url):
        return path_or_url
    if not path_or_url.startswith('http'):
        raise FileNotFoundError(path_or_url)

    # try gdown if available
    try:
        import gdown
    except Exception:
        raise RuntimeError('URL input requires gdown to be installed. Install with: pip install gdown')

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.basename(path_or_url))
    out = tmp.name
    tmp.close()
    print('Downloading to', out)
    gdown.download(path_or_url, out, quiet=False)
    return out


def load_ndjson(path: str) -> list:
    entries = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
                entries.append(j)
            except Exception:
                # try to fix trailing commas etc
                try:
                    j = json.loads(line.replace("'", '"'))
                    entries.append(j)
                except Exception:
                    continue
    return entries


def extract_row(entry: dict) -> dict:
    # Pull core fields with safe fallbacks
    # Minimal safe extraction. Keep additional fields that are useful for analysis.
    ts = entry.get('timestamp') or entry.get('time')
    try:
        ts_parsed = pd.to_datetime(ts)
    except Exception:
        ts_parsed = pd.to_datetime(entry.get('timestamp', pd.NaT))

    out = {
        'timestamp': ts_parsed,
        'symbol': entry.get('symbol') or entry.get('system') or entry.get('sym'),
        'entry_price': entry.get('entry_price'),
        'decision': entry.get('decision'),
        'rating': entry.get('rating'),
        # optional screener metadata (may contain 'symbol_used')
        'screener': entry.get('screener'),
    }
    # copy through any other keys we commonly inspect
    if 'rsi' in entry:
        out['rsi'] = entry.get('rsi')
    return out


def compute_forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a DataFrame with at least columns: timestamp, symbol, entry_price, screener (optional),
    attempt to compute ret_1h, ret_6h, ret_24h using yfinance.
    This function will try multiple candidate tickers (from YF_SYMBOL_MAP) and use a daily
    fallback or entry_price fallback where appropriate. Returns an expanded DataFrame.
    """
    rows = []

    for _, r in df.iterrows():
        rdict = dict(r)
        ts = rdict.get('timestamp')
        sym = rdict.get('symbol')

        # Prepare candidates: prefer screener symbol if present
        candidates = []
        screener = rdict.get('screener') or {}
        screener_sym = screener.get('symbol_used') if isinstance(screener, dict) else None
        if screener_sym:
            candidates.append(screener_sym)

        yf_map_val = YF_SYMBOL_MAP.get(sym)
        if isinstance(yf_map_val, (list, tuple)):
            for c in yf_map_val:
                if c not in candidates:
                    candidates.append(c)
        elif isinstance(yf_map_val, str):
            if yf_map_val not in candidates:
                candidates.append(yf_map_val)

        rdict['yf_sym_candidates'] = ','.join(candidates)
        rdict['candidate_used'] = None
        rdict['daily_candidate_used'] = None
        rdict['hist_rows'] = None
        rdict['daily_rows'] = None
        rdict['hist_empty'] = None
        rdict['daily_empty'] = None
        rdict['nearest_diff_seconds'] = None
        rdict['hist_available'] = False

        if not candidates:
            for h in FORWARD_HOURS:
                rdict[f'ret_{h}h'] = None
            rows.append(rdict)
            continue

        # Try hourly data for candidates (3d then 7d)
        hist = None
        used_candidate = None
        for cand in candidates:
            try:
                hist_tmp = yf.download(cand, period='3d', interval='1h', progress=False, auto_adjust=True)
                if hist_tmp is not None and not hist_tmp.empty:
                    hist = hist_tmp
                    used_candidate = cand
                    break
            except Exception:
                continue

        if hist is None:
            for cand in candidates:
                try:
                    hist_tmp = yf.download(cand, period='7d', interval='1h', progress=False, auto_adjust=True)
                    if hist_tmp is not None and not hist_tmp.empty:
                        hist = hist_tmp
                        used_candidate = cand
                        break
                except Exception:
                    continue

        # Try daily if hourly missing
        daily = None
        used_daily = None
        if hist is None:
            for cand in candidates:
                try:
                    daily_tmp = yf.download(cand, period='30d', interval='1d', progress=False, auto_adjust=True)
                    if daily_tmp is not None and not daily_tmp.empty:
                        daily = daily_tmp
                        used_daily = cand
                        break
                except Exception:
                    continue

        rdict['candidate_used'] = used_candidate
        rdict['daily_candidate_used'] = used_daily
        try:
            rdict['hist_rows'] = int(getattr(hist, 'shape', (0, 0))[0]) if hist is not None and not hist.empty else 0
        except Exception:
            rdict['hist_rows'] = None
        try:
            rdict['daily_rows'] = int(getattr(daily, 'shape', (0, 0))[0]) if daily is not None and not daily.empty else 0
        except Exception:
            rdict['daily_rows'] = None
        rdict['hist_empty'] = hist is None or (hasattr(hist, 'empty') and hist.empty)
        rdict['daily_empty'] = daily is None or (hasattr(daily, 'empty') and daily.empty)

        base_price = None

        # If hourly data available, normalize and try nearest-match
        if hist is not None and not hist.empty:
            try:
                hist_index = pd.to_datetime(hist.index)
                if getattr(hist_index, 'tz', None) is not None:
                    hist_index = hist_index.tz_convert(None)
                hist.index = hist_index
            except Exception:
                hist.index = pd.to_datetime(hist.index)

            try:
                ts_norm = pd.to_datetime(ts)
                if getattr(ts_norm, 'tz', None) is not None:
                    ts_norm = ts_norm.tz_convert(None)
            except Exception:
                ts_norm = pd.to_datetime(ts)

            try:
                pos = hist.index.get_indexer([ts_norm], method='nearest')[0]
                if pos is not None and 0 <= pos < len(hist):
                    nearest_time = hist.index[pos]
                    try:
                        diff_seconds = abs((nearest_time - ts_norm).total_seconds())
                    except Exception:
                        diff_seconds = None
                    rdict['nearest_diff_seconds'] = diff_seconds
                    if diff_seconds is None or diff_seconds > NEAREST_THRESHOLD_SECONDS:
                        # treat hourly as unavailable and attempt daily fallback
                        rdict['hist_available'] = False
                    else:
                        base_price = hist['Close'].iat[pos]
                        rdict['hist_available'] = True
                else:
                    rdict['hist_available'] = False
            except Exception:
                rdict['hist_available'] = False

        # If hourly not available, try daily fallback for 24h
        if not rdict['hist_available'] and (daily is not None and not daily.empty):
            try:
                daily.index = pd.to_datetime(daily.index).normalize()
            except Exception:
                daily.index = pd.to_datetime(daily.index)
            try:
                ts_day = pd.to_datetime(ts).normalize()
            except Exception:
                ts_day = pd.to_datetime(ts)
            try:
                base_idx = daily.index.get_indexer([ts_day], method='nearest')[0]
                future_idx = daily.index.get_indexer([ts_day + pd.Timedelta(days=1)], method='nearest')[0]
                base_price_daily = daily['Close'].iat[base_idx]
                future_price_daily = daily['Close'].iat[future_idx]
                # Use entry_price as base if hourly base_price not available
                base_for_24 = base_price if base_price is not None else (rdict.get('entry_price') or base_price_daily)
                if base_for_24 and future_price_daily:
                    rdict['ret_24h'] = (future_price_daily - base_for_24) / base_for_24
                else:
                    rdict['ret_24h'] = None
            except Exception:
                rdict['ret_24h'] = None
            # 1h/6h not available from daily
            rdict['ret_1h'] = None
            rdict['ret_6h'] = None
            rows.append(rdict)
            continue

        # If we have an hourly histogram and a base_price (or fallback to entry_price), compute forward returns
        if rdict['hist_available'] and (hist is not None and not hist.empty):
            try:
                ts_norm = pd.to_datetime(ts)
                if getattr(ts_norm, 'tz', None) is not None:
                    ts_norm = ts_norm.tz_convert(None)
            except Exception:
                ts_norm = pd.to_datetime(ts)

            if base_price is None:
                base_price = rdict.get('entry_price')

            for h in FORWARD_HOURS:
                future_t = ts_norm + pd.Timedelta(hours=h)
                try:
                    posf = hist.index.get_indexer([future_t], method='nearest')[0]
                    if posf is not None and 0 <= posf < len(hist):
                        future_price = hist['Close'].iat[posf]
                        if base_price and future_price:
                            rdict[f'ret_{h}h'] = (future_price - base_price) / base_price
                        else:
                            rdict[f'ret_{h}h'] = None
                    else:
                        rdict[f'ret_{h}h'] = None
                except Exception:
                    rdict[f'ret_{h}h'] = None

            rows.append(rdict)
            continue

        # Last resort: no hist and no daily -> we cannot compute future prices; leave None
        for h in FORWARD_HOURS:
            rdict[f'ret_{h}h'] = None
        rows.append(rdict)

    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, outdir: str):
    os.makedirs(outdir, exist_ok=True)
    # basic counts
    totals = df['decision'].value_counts(dropna=False).to_dict() if 'decision' in df.columns else {}

    # rating distribution
    rating_stats = df['rating'].describe().to_dict() if 'rating' in df.columns else {}

    # per-decision forward returns
    per_decision = {}
    if 'decision' in df.columns:
        for dec in df['decision'].dropna().unique():
            sub = df[df['decision'] == dec]
            stats = {
                'count': int(len(sub)),
                'mean_rating': float(sub['rating'].mean()) if ('rating' in sub.columns and not sub['rating'].isna().all()) else None,
            }
        for h in FORWARD_HOURS:
            col = f'ret_{h}h'
            stats[f'mean_ret_{h}h'] = float(sub[col].dropna().mean()) if col in sub.columns else None
            stats[f'winrate_{h}h'] = float((sub[col] > 0).sum() / sub[col].dropna().shape[0]) if col in sub.columns and sub[col].dropna().shape[0] > 0 else None
        per_decision[dec] = stats

    # correlation matrices
    corr = {}
    for h in FORWARD_HOURS:
        col = f'ret_{h}h'
        if col in df.columns:
            # compute correlations only if the required columns exist
            rating_corr = None
            rsi_corr = None
            if 'rating' in df.columns and not df[['rating', col]].dropna().empty:
                rating_corr = df[['rating', col]].dropna().corr().iloc[0,1]
            if 'rsi' in df.columns and not df[['rsi', col]].dropna().empty:
                rsi_corr = df[['rsi', col]].dropna().corr().iloc[0,1]
            corr[col] = {'rating_corr': rating_corr, 'rsi_corr': rsi_corr}
        else:
            corr[col] = {'rating_corr': None, 'rsi_corr': None}

    # write CSVs
    df.to_csv(os.path.join(outdir, 'ifd_rows_expanded.csv'), index=False)
    pd.DataFrame.from_dict(per_decision, orient='index').to_csv(os.path.join(outdir, 'per_decision_summary.csv'))

    # simple markdown report
    md = []
    md.append('# IFD Performance Report')
    md.append(f'Date: {dt.datetime.utcnow().isoformat()}')
    md.append('## Totals')
    for k, v in totals.items():
        md.append(f'- {k}: {v}')
    md.append('\n## Rating stats')
    for k, v in rating_stats.items():
        md.append(f'- {k}: {v}')
    md.append('\n## Per-decision summary')
    for dec, vals in per_decision.items():
        md.append(f'### {dec}')
        for kk, vv in vals.items():
            md.append(f'- {kk}: {vv}')
    md.append('\n## Correlations (forward returns)')
    for col, vv in corr.items():
        md.append(f'- {col}: rating_corr={vv.get("rating_corr")}, rsi_corr={vv.get("rsi_corr")}')

    with open(os.path.join(outdir, 'report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    print('Wrote report to', outdir)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', '-i', required=True, help='Path to ifd_orders.jsonl or a public URL')
    p.add_argument('--outdir', '-o', default=None, help='Output directory for analysis')
    args = p.parse_args()

    inp = args.input
    try:
        path = download_if_needed(inp)
    except Exception as e:
        if os.path.exists(inp):
            path = inp
        else:
            print('Failed to download input:', e)
            sys.exit(2)

    entries = load_ndjson(path)
    rows = [extract_row(e) for e in entries]
    df = pd.DataFrame(rows)

    # compute forward returns
    df2 = compute_forward_returns(df)

    outdir = args.outdir or os.path.join('output', 'analysis_' + dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S'))
    summarize(df2, outdir)


if __name__ == '__main__':
    main()
