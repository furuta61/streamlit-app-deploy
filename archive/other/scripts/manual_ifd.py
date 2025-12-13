#!/usr/bin/env python3
"""Create a strict-format IFD JSON line and append to output/ifd_orders.jsonl.

Usage examples:
  python3 scripts/manual_ifd.py --symbol XAUUSD --side buy --entry 4143.6 \
    --sl 4076.4 --tp1 4175.9 --tp2 4192.0 --order_type LIMIT --decision STRONG_GO \
    --trusted_csv false --lots 6

The script will backup `output/ifd_orders.jsonl` before appending.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / 'output' / 'ifd_orders.jsonl'


def build_ifd(symbol: str, side: str, entry: float, sl: float, tp1: float, tp2: float, order_type: str, decision: str, trusted_csv: bool, lots: int):
    # Normalize
    side = side.lower()
    obj = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'instrument': symbol,
        'side': 'BUY' if side in ('buy','b') else 'SELL',
        'decision': decision,
        'order_type': order_type.upper(),
        'trusted_csv': bool(trusted_csv),
        'lots': int(lots),
        'entry_price': float(entry),
        'ifd_legs': [
            {
                'name': 'IFD-1',
                'oco': {
                    'take_profit': {'price': float(tp1)},
                    'stop_loss': {'price': float(sl)}
                }
            },
            {
                'name': 'IFD-2',
                'oco': {
                    'take_profit': {'price': float(tp2)},
                    'stop_loss': {'price': float(sl)}
                }
            }
        ]
    }
    return obj


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_suffix(path.suffix + f'.bak_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
    shutil.copy2(path, backup)
    return backup


def append_line(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(line + "\n")


def parse_bool(v: str) -> bool:
    return str(v).lower() in ('1','true','yes','y','t')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--symbol', required=True)
    p.add_argument('--side', default='buy')
    p.add_argument('--entry', type=float, required=True)
    p.add_argument('--sl', type=float, required=True)
    p.add_argument('--tp1', type=float, required=True)
    p.add_argument('--tp2', type=float, required=True)
    p.add_argument('--order_type', default='LIMIT')
    p.add_argument('--decision', default='GO')
    p.add_argument('--trusted_csv', default='false')
    p.add_argument('--lots', type=int, default=1)
    args = p.parse_args()

    trusted = parse_bool(args.trusted_csv)

    print(f"Backing up {OUT_FILE} (if exists) and appending new IFD for {args.symbol}...")
    b = backup_file(OUT_FILE)
    if b:
        print(f"Backup created: {b}")
    else:
        print("No existing orders file to backup; will create new one.")

    obj = build_ifd(args.symbol, args.side, args.entry, args.sl, args.tp1, args.tp2, args.order_type, args.decision, trusted, args.lots)
    append_line(OUT_FILE, obj)
    print(f"Appended to {OUT_FILE}:")
    print(json.dumps(obj, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
