#!/usr/bin/env python3
"""
dividend_report.py

Fetch recent dividend history for given symbols (yfinance) and write a small report to output/
"""
import argparse
from pathlib import Path
import yfinance as yf
import datetime as dt
import csv

OUT = Path('output')
OUT.mkdir(exist_ok=True)

def run(symbols, days=365):
    end = dt.datetime.now()
    start = end - dt.timedelta(days=days)
    rows = []
    for s in symbols:
        tk = yf.Ticker(s)
        try:
            df = tk.dividends
            if df is None or df.empty:
                rows.append({'symbol': s, 'has_dividends': False})
                continue
            # filter by date
            df = df[df.index.date >= start.date()]
            for idx, val in df.iteritems():
                rows.append({'symbol': s, 'date': idx.date().isoformat(), 'amount': float(val)})
        except Exception as e:
            rows.append({'symbol': s, 'error': str(e)})

    out_path = OUT / f'dividend_report_{dt.datetime.utcnow().strftime("%Y%m%d_%H%M")}.csv'
    keys = set().union(*(r.keys() for r in rows)) if rows else ['symbol']
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(keys))
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print('Wrote', out_path)
    return out_path

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--symbols', nargs='+', default=['1321.T','^N225','AAPL'])
    p.add_argument('--days', type=int, default=365)
    args = p.parse_args()
    run(args.symbols, days=args.days)

if __name__ == '__main__':
    main()
