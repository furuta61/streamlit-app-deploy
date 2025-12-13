#!/usr/bin/env python3
"""
apply_broker_scale.py

Read `output/ifd_proposals.json` (or another JSON proposals file) and apply
broker-specific scaling/rounding rules from `configs/broker_price_map.yaml`.

By default this writes `output/ifd_proposals_broker_scaled.json` and leaves
the original file untouched (but creates a timestamped backup if --inplace).

Usage examples:
  python scripts/apply_broker_scale.py --input output/ifd_proposals.json
  python scripts/apply_broker_scale.py --inplace

"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import yaml


def load_config(path='configs/broker_price_map.yaml'):
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def find_config_for_instrument(cfg, instr: str):
    if not cfg:
        return None
    for key, v in cfg.items():
        aliases = v.get('symbol_aliases', [])
        if instr == key or instr in aliases:
            return v
    return None


def quantize_price(price: float, decimals: int) -> float:
    q = Decimal(str(price))
    exp = Decimal('1').scaleb(-decimals)
    return float(q.quantize(exp, rounding=ROUND_HALF_UP))


def apply_scale_to_entry(entry: dict, cfg_entry: dict, stats: dict, dry_run: bool=False):
    """Apply scaling to numeric price fields in entry.

    To improve precision, skip scaling for a field if the existing value already
    matches the broker's display decimals (i.e. appears to be broker-aligned).
    """
    factor = float(cfg_entry.get('scale_factor', 1.0))
    decimals = int(cfg_entry.get('display_decimals', 6))
    # Safe epsilon for float comparisons after quantization
    eps = 10 ** (-decimals) / 2
    for field in ('entry_price', 'take_profit', 'stop_loss'):
        if field in entry and entry[field] is not None:
            orig = float(entry[field])
            # If the value already matches quantized display, consider it broker-aligned
            quant = quantize_price(orig, decimals)
            if abs(orig - quant) <= eps:
                stats['skipped'] += 1
                stats['skipped_fields'].append((entry.get('instrument'), field, orig))
                continue
            # If factor is 1.0, nothing to do
            if abs(factor - 1.0) < 1e-12:
                stats['skipped'] += 1
                stats['skipped_fields'].append((entry.get('instrument'), field, orig))
                continue
            newp = float(orig) * factor
            newq = quantize_price(newp, decimals)
            stats['applied'] += 1
            stats['applied_fields'].append((entry.get('instrument'), field, orig, newq))
            if not dry_run:
                entry[field] = newq
    # Also adjust any nested IFD legs
    if 'ifd_legs' in entry and isinstance(entry['ifd_legs'], list):
        for leg in entry['ifd_legs']:
            # look for oco->take_profit / stop_loss
            oco = leg.get('oco') or {}
            tp = oco.get('take_profit')
            sl = oco.get('stop_loss')
            if isinstance(tp, dict) and 'price' in tp:
                tp['price'] = quantize_price(float(tp['price']) * factor, decimals)
            if isinstance(sl, dict) and 'price' in sl:
                sl['price'] = quantize_price(float(sl['price']) * factor, decimals)
    return entry


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', '-i', default='output/ifd_proposals.json')
    p.add_argument('--output', '-o', default='output/ifd_proposals_broker_scaled.json')
    p.add_argument('--config', '-c', default='configs/broker_price_map.yaml')
    p.add_argument('--inplace', action='store_true', help='overwrite input file (backup created)')
    p.add_argument('--dry-run', action='store_true', help='do not modify entries, only report what would change')
    args = p.parse_args()

    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}")
        return

    cfg = load_config(args.config)

    with open(args.input, 'r') as f:
        data = json.load(f)

    # data expected to be list or dict with top-level list under 'orders' or 'proposals'
    proposals = []
    if isinstance(data, dict):
        if 'orders' in data and isinstance(data['orders'], list):
            proposals = data['orders']
        elif 'proposals' in data and isinstance(data['proposals'], list):
            proposals = data['proposals']
        else:
            # single-entry dict -> treat as single proposal
            proposals = [data]
    elif isinstance(data, list):
        proposals = data

    stats = {'applied': 0, 'skipped': 0, 'applied_fields': [], 'skipped_fields': []}
    for entry in proposals:
        instr = entry.get('instrument') or entry.get('symbol')
        if not instr:
            continue
        conf = find_config_for_instrument(cfg, instr)
        if conf:
            apply_scale_to_entry(entry, conf, stats, dry_run=args.dry_run)


    # Decide where to write
    if args.inplace:
        bak = f"{args.input}.bak_before_broker_scale_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
        shutil.copy2(args.input, bak)
        with open(args.input, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Wrote inplace scaled file and created backup: {bak}")
    else:
        with open(args.output, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Wrote scaled proposals to: {args.output}")

    print(f"Applied broker scaling: applied_fields={len(stats['applied_fields'])}, skipped_fields={len(stats['skipped_fields'])}")
    if stats['applied_fields']:
        print("Sample applied changes:")
        for s in stats['applied_fields'][:10]:
            inst, field, old, new = s
            print(f"  {inst} {field}: {old} -> {new}")
    if stats['skipped_fields']:
        print("Sample skipped fields (already broker-aligned or no-op):")
        for s in stats['skipped_fields'][:10]:
            inst, field, old = s
            print(f"  {inst} {field}: {old}")


if __name__ == '__main__':
    main()
