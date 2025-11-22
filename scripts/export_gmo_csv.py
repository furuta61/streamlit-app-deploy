#!/usr/bin/env python3
"""
export_gmo_csv.py

Create a CSV for manual GMO CFD entry from current `output/ifd_orders.jsonl`.

Columns: Symbol,Side,OrderType,Entry,TP,SL,Qty,Comment

Assumptions:
- Decisions 'GO'/'STRONG_GO' -> buy ('買'). Others -> skip by default.
- Default quantities are conservative suggestions; adjust to your account/margin.
"""
import csv
import json
import sys
from pathlib import Path
# ensure repo root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from mygpt_strategy import ROUND_DIGITS

INPUT = Path(__file__).resolve().parents[1] / 'output' / 'ifd_orders.jsonl'
OUT = Path(__file__).resolve().parents[1] / 'output' / 'ifd_orders_gmo.csv'

DEFAULT_QTY = {
    'JP225': 1,
    'NQ100': 1,
    'GER40': 1,
    'XAUUSD': 0.1,
    'XAGUSD': 1,
    'NGAS': 1,
}

def round_for(sym, val):
    rd = ROUND_DIGITS.get(sym, 2)
    if isinstance(val, float):
        return f"{val:.{rd}f}"
    return str(val)

if not INPUT.exists():
    print('No input file:', INPUT)
    raise SystemExit(1)

# collect latest entry per symbol
latest = {}
with INPUT.open('r', encoding='utf-8') as f:
    for line in f:
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        sym = obj.get('symbol')
        if not sym:
            continue
        ts = obj.get('timestamp') or obj.get('time')
        # fallback: if no timestamp, treat as older
        if ts is None:
            key = (sym, 0)
            cur_ts = 0
        else:
            try:
                # compare lexicographically or as ISO
                cur_ts = ts
            except Exception:
                cur_ts = ts
        prev = latest.get(sym)
        if prev is None:
            latest[sym] = (cur_ts, obj)
        else:
            # compare timestamps lexicographically (ISO format)
            if cur_ts and prev[0] and str(cur_ts) > str(prev[0]):
                latest[sym] = (cur_ts, obj)

rows = []
for sym, (_, obj) in latest.items():
    decision = obj.get('decision','').upper()
    if decision not in ('GO','STRONG_GO'):
        # skip non-buy signals by default
        continue
    entry = obj.get('entry_price')
    tp = obj.get('take_profit')
    sl = obj.get('stop_loss')
    rating = obj.get('rating')
    side = '買' if decision in ('GO','STRONG_GO') else '売'
    order_type = 'IFD'
    qty = DEFAULT_QTY.get(sym, 1)
    comment = f"decision={decision};rating={rating}"
    rows.append({
        'Symbol': sym,
        'Side': side,
        'OrderType': order_type,
        'Entry': round_for(sym, entry),
        'TP': round_for(sym, tp),
        'SL': round_for(sym, sl),
        'Qty': qty,
        'Comment': comment,
    })

with OUT.open('w', encoding='utf-8', newline='') as csvfile:
    fieldnames = ['Symbol','Side','OrderType','Entry','TP','SL','Qty','Comment']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

print('Wrote', OUT, 'rows=', len(rows))
