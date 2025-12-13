#!/usr/bin/env python3
"""Generate synthetic 60m and 240m CSVs for US30 and COPPER under ./data.

Creates files with headers: time,open,high,low,close,volume
Generates a smooth random-walk trend so indicators can be computed.
"""
from pathlib import Path
from datetime import datetime, timedelta
import random
import csv
import sys

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./data")
OUT.mkdir(parents=True, exist_ok=True)

def gen_series(n, start_dt, delta, start_price, volatility=0.002, volume_base=100000):
    rows = []
    price = float(start_price)
    for i in range(n):
        dt = start_dt + i * delta
        # small drift upward
        drift = 1 + (random.random() - 0.45) * volatility
        openp = price
        closep = openp * drift
        high = max(openp, closep) * (1 + random.random() * 0.0015)
        low = min(openp, closep) * (1 - random.random() * 0.0015)
        volume = int(volume_base * (0.5 + random.random()))
        rows.append((dt.isoformat() + "+00:00", f"{openp:.4f}", f"{high:.4f}", f"{low:.4f}", f"{closep:.4f}", str(volume)))
        price = closep
    return rows

def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['time','open','high','low','close','volume'])
        for r in rows:
            w.writerow(r)
    print(f"wrote {path}")

def make_for(symbol, start_price, hours240=240, hours60=480):
    # hours240 = number of 4h bars to generate
    now = datetime.utcnow()
    # 240-min bars: generate hours240 bars at 4-hour intervals, oldest first
    delta4 = timedelta(hours=4)
    start4 = now - (hours240-1) * delta4
    rows4 = gen_series(hours240, start4, delta4, start_price, volatility=0.003, volume_base=200000)
    # 60-min bars
    delta1 = timedelta(hours=1)
    start1 = now - (hours60-1) * delta1
    rows1 = gen_series(hours60, start1, delta1, start_price, volatility=0.0025, volume_base=80000)

    # write files with naming patterns similar to existing files (use _241/_31 to match others)
    p4 = OUT / symbol / f"{symbol}_241.csv"
    p1 = OUT / symbol / f"{symbol}_31.csv"
    write_csv(p4, rows4)
    write_csv(p1, rows1)
    # also create top-level copies for convenience
    tl4 = OUT / f"{symbol}_240.csv"
    tl1 = OUT / f"{symbol}_60.csv"
    # remove if exist
    if tl4.exists():
        tl4.unlink()
    if tl1.exists():
        tl1.unlink()
    tl4.symlink_to(p4)
    tl1.symlink_to(p1)
    print(f"symlinked {tl4} -> {p4}")

def main():
    random.seed(42)
    make_for('US30', start_price=36000.0, hours240=200, hours60=400)
    # copper price around 4.5 USD per lb scaled; use 4.5
    make_for('XCUUSD', start_price=4.50, hours240=200, hours60=400)

if __name__ == '__main__':
    main()
