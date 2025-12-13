#!/usr/bin/env python3
"""
tv_to_csv_sync.py

Simple utility to sync `output/tradingview.jsonl` (or another TV jsonl file)
into per-symbol canonical CSV files under `data/` named `<SYMBOL>_240.csv`.

Behavior (safe/default):
 - read lines from input jsonl (default: output/tradingview.jsonl)
 - for each record containing {"data": {"symbol":..., "price":..., "timestamp":...}} write an append-only CSV
 - CSV columns: timestamp,price
 - If file doesn't exist, create with header. If last timestamp equals current, skip duplicate.

This is intentionally minimal and conservative (no destructive updates).
"""
from __future__ import annotations

import argparse
import json
import os
import csv
from datetime import datetime


def parse_tv_line(line: str) -> dict | None:
    try:
        obj = json.loads(line)
    except Exception:
        return None
    # Try common shapes
    if isinstance(obj, dict):
        # Some records may include 'incoming_payload' or 'data'
        if 'data' in obj and isinstance(obj['data'], dict):
            data = obj['data']
            # allow nested 'price' and 'symbol'
            if 'symbol' in data and 'price' in data:
                # timestamp could be under data.timestamp or top-level 'timestamp'
                ts = data.get('timestamp') or obj.get('timestamp') or data.get('time')
                return {'symbol': data['symbol'], 'price': float(data['price']), 'timestamp': ts}
        # fallback to top-level
        if 'symbol' in obj and 'price' in obj:
            return {'symbol': obj['symbol'], 'price': float(obj['price']), 'timestamp': obj.get('timestamp')}
    return None


def safe_write_csv(path: str, timestamp: str, price: float):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_header = not os.path.exists(path)
    # Check duplicate last line
    if not write_header:
        try:
            with open(path, 'r', newline='') as f:
                last = None
                for last in f:
                    pass
                if last:
                    last = last.strip().split(',')
                    if len(last) >= 2 and last[0] == timestamp:
                        return False
        except Exception:
            pass

    with open(path, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        if write_header:
            writer.writerow(['timestamp', 'price'])
        writer.writerow([timestamp, '{:.8f}'.format(price)])
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', '-i', default='output/tradingview.jsonl')
    p.add_argument('--outdir', '-o', default='data')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()

    created = 0
    processed = 0

    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}")
        return

    with open(args.input, 'r') as fh:
        for ln in fh:
            rec = parse_tv_line(ln)
            if not rec:
                continue
            processed += 1
            symbol = rec['symbol'].replace('/', '_')
            timestamp = rec['timestamp'] or datetime.utcnow().isoformat()
            price = float(rec['price'])
            outpath = os.path.join(args.outdir, f"{symbol}_240.csv")
            if args.dry_run:
                print(f"Would write: {outpath} <- {timestamp},{price}")
            else:
                ok = safe_write_csv(outpath, timestamp, price)
                if ok:
                    created += 1

    print(f"Processed {processed} records; wrote {created} new rows.")


if __name__ == '__main__':
    main()
