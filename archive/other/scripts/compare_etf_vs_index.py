#!/usr/bin/env python3
"""
compare_etf_vs_index.py

Quick script to compare an ETF (e.g. 1321.T) against the Nikkei index (^N225)
using yfinance historical daily closes. Outputs mean absolute % difference,
max absolute % difference and Pearson correlation for the overlapping period.

Usage:
  ./.venv/bin/python3 scripts/compare_etf_vs_index.py --etf 1321.T --index ^N225 --days 90

This helps decide whether an ETF is an acceptable proxy for the official index
for monitoring and signal generation purposes.
"""
import argparse
import datetime as dt
import sys
import warnings
import os

try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except Exception as e:
    raise RuntimeError("Please install requirements: pip install yfinance pandas numpy") from e


def fetch_close(symbol: str, days: int):
    end = dt.datetime.now()
    start = end - dt.timedelta(days=days)
    tk = yf.Ticker(symbol)
    hist = tk.history(start=start.date(), end=end.date(), interval='1d')
    if hist is None or hist.empty:
        return pd.Series(dtype=float)
    s = hist['Close'].copy()
    s.index = pd.to_datetime(s.index).date
    s.name = symbol
    return s


def compare(etf: str, index_sym: str, days: int = 90):
    s_etf = fetch_close(etf, days)
    s_idx = fetch_close(index_sym, days)

    if s_etf.empty:
        print(f"ETF series empty for {etf}")
        return 2
    if s_idx.empty:
        print(f"Index series empty for {index_sym}")
        return 2

    df = pd.concat([s_etf, s_idx], axis=1, join='inner').dropna()
    if df.empty:
        print("No overlapping dates between ETF and index series")
        return 2

    # absolute percent differences (ETF relative to index)
    df['pct_diff'] = (df[etf] - df[index_sym]) / df[index_sym].replace(0, np.nan)
    abs_pct = df['pct_diff'].abs() * 100.0

    mean_abs_pct = abs_pct.mean()
    max_abs_pct = abs_pct.max()
    corr = df[etf].corr(df[index_sym])

    print(f"Compared {etf} vs {index_sym} over {len(df)} overlapping days")
    print(f"Mean absolute % difference: {mean_abs_pct:.4f}%")
    print(f"Max absolute % difference: {max_abs_pct:.4f}%")
    print(f"Pearson correlation: {corr:.6f}")

    # show a few worst days
    worst = df.assign(abs_pct=abs_pct).sort_values('abs_pct', ascending=False).head(10)
    print('\nTop 10 worst days (date, ETF, INDEX, abs%):')
    for d, row in worst.iterrows():
        print(f"{d}: {row[etf]:.2f}, {row[index_sym]:.2f}, {row['abs_pct']:.4f}%")

    # Decision logic: if mean or max exceed thresholds, recommend high-accuracy mode
    # Thresholds are conservative defaults: mean 0.5% and max 1.5%
    mean_threshold = float(os.getenv('ETF_MEAN_THRESHOLD_PCT', '0.5'))
    max_threshold = float(os.getenv('ETF_MAX_THRESHOLD_PCT', '1.5'))

    decision = 'ok'
    if mean_abs_pct > mean_threshold or max_abs_pct > max_threshold:
        decision = 'use_high_accuracy'

    # Write decision to output file for automation
    out = {
        'etf': etf,
        'index': index_sym,
        'days': int(len(df)),
        'mean_abs_pct': float(mean_abs_pct),
        'max_abs_pct': float(max_abs_pct),
        'pearson_corr': float(corr),
        'decision': decision,
        'mean_threshold_pct': mean_threshold,
        'max_threshold_pct': max_threshold,
        'timestamp': dt.datetime.utcnow().isoformat() + 'Z'
    }

    import os as _os, json as _json
    out_dir = _os.path.join(_os.getcwd(), 'output')
    try:
        _os.makedirs(out_dir, exist_ok=True)
    except Exception:
        pass

    out_path = _os.path.join(out_dir, 'high_accuracy_decision.json')
    with open(out_path, 'w') as f:
        _json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"\nDecision written to: {out_path} (decision={decision})")

    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--etf', default='1321.T', help='ETF ticker on yfinance (e.g. 1321.T)')
    p.add_argument('--index', default='^N225', help='Index ticker on yfinance (e.g. ^N225)')
    p.add_argument('--days', type=int, default=90, help='Lookback in days')
    args = p.parse_args()

    try:
        return compare(args.etf, args.index, args.days)
    except Exception as e:
        warnings.warn(str(e))
        return 1


if __name__ == '__main__':
    sys.exit(main())
