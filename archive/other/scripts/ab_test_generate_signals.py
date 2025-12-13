#!/usr/bin/env python3
"""
ab_test_generate_signals.py

Generate a simple signals CSV using `trend_analyzer.calculate_trend_signals` for a set of symbols and save to output/
This can be used to compare against CSV/スクショGPT outputs for A/B testing.
"""
import argparse
import datetime as dt
import os
import csv
from pathlib import Path

import pandas as pd

from trend_analyzer import calculate_trend_signals

OUT_DIR = Path('output')
OUT_DIR.mkdir(exist_ok=True)

def run(symbols, period='5d', interval='1h'):
    rows = []
    ts = dt.datetime.utcnow().strftime('%Y%m%d_%H%M')
    for s in symbols:
        try:
            res = calculate_trend_signals(s, period=period, interval=interval)
            if 'error' in res:
                row = {'symbol': s, 'error': res['error']}
            else:
                row = {
                    'symbol': s,
                    'direction': res.get('direction'),
                    'strength': res.get('strength'),
                    'current_price': res.get('current_price'),
                    'ensemble_price': res.get('ensemble_price') if 'ensemble_price' in res else '',
                    'ensemble_confidence': res.get('ensemble_confidence') if 'ensemble_confidence' in res else ''
                }
        except Exception as e:
            row = {'symbol': s, 'error': str(e)}
        rows.append(row)

    out_path = OUT_DIR / f'ab_signals_{ts}.csv'
    keys = set().union(*(r.keys() for r in rows))
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(keys))
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print('Wrote', out_path)
    return out_path

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--symbols', nargs='+', default=['JP225','DE40','NASDAQ_MINI','AAPL','MSFT','GOLD_SPOT'])
    p.add_argument('--period', default='5d')
    p.add_argument('--interval', default='1h')
    args = p.parse_args()
    run(args.symbols, period=args.period, interval=args.interval)

if __name__ == '__main__':
    main()
