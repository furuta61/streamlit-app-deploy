#!/usr/bin/env python3
import json
import os
import csv

ROOT = os.path.dirname(os.path.dirname(__file__))
IFD_FP = os.path.join(ROOT, 'output', 'ifd_proposals.json')
OUT_CSV = os.path.join(ROOT, 'output', 'ifd_analysis.csv')
OUT_JSON = os.path.join(ROOT, 'output', 'ifd_analysis.json')

# Mirror of generate_ifd provisional maps (should be kept in sync)
POINT_VALUE_MAP = {
    'JP225': 100,
    'NAS100': 20,
    'US30': 100,
    'XAUUSD': 150,
    'COPPER': 1000,
}

DECIMALS = {
    'JP225': 0,
    'NAS100': 0,
    'US30': 0,
    'XAUUSD': 2,
    'COPPER': 3,
}

if not os.path.exists(IFD_FP):
    print('IFD proposals not found at', IFD_FP)
    raise SystemExit(1)

with open(IFD_FP, 'r', encoding='utf-8') as f:
    j = json.load(f)

orders = j.get('orders', [])
rows = []
for o in orders:
    inst = o.get('instrument')
    dec = o.get('decision')
    lots = o.get('lots')
    entry = o.get('entry_price')
    legs = o.get('ifd_legs', [])
    tp1 = None
    tp2 = None
    sl = None
    try:
        tp1 = legs[0]['oco']['take_profit']['price']
    except Exception:
        tp1 = ''
    try:
        sl = legs[0]['oco']['stop_loss']['price']
    except Exception:
        sl = ''
    try:
        tp2 = legs[1]['oco']['take_profit']['price']
    except Exception:
        tp2 = ''

    # numeric conversions
    try:
        entry_f = float(entry)
    except Exception:
        entry_f = None
    try:
        tp1_f = float(tp1)
    except Exception:
        tp1_f = None
    try:
        tp2_f = float(tp2)
    except Exception:
        tp2_f = None
    try:
        sl_f = float(sl)
    except Exception:
        sl_f = None

    # compute deltas in points (abs)
    d1 = None
    d2 = None
    jpy_tp1 = None
    jpy_tp2 = None
    pv = POINT_VALUE_MAP.get(inst)
    if entry_f is not None and tp1_f is not None:
        d1 = abs(tp1_f - entry_f)
        if pv:
            jpy_tp1 = d1 * pv
    if entry_f is not None and tp2_f is not None:
        d2 = abs(tp2_f - entry_f)
        if pv:
            jpy_tp2 = d2 * pv

    # rounding per decimals
    dec = DECIMALS.get(inst, 2)
    def fmt(v):
        if v is None:
            return ''
        if dec == 0:
            return str(int(round(v)))
        return f"{round(v, dec):.{dec}f}"

    row = {
        'instrument': inst,
        'decision': dec,
        'lots': lots,
        'entry': fmt(entry_f),
        'tp1': fmt(tp1_f),
        'tp2': fmt(tp2_f),
        'sl': fmt(sl_f),
        'delta_tp1_points': f"{d1:.4f}" if d1 is not None else '',
        'delta_tp2_points': f"{d2:.4f}" if d2 is not None else '',
        'jpy_per_lot_tp1': f"{jpy_tp1:.2f}" if jpy_tp1 is not None else '',
        'jpy_per_lot_tp2': f"{jpy_tp2:.2f}" if jpy_tp2 is not None else '',
    }
    rows.append(row)

# write CSV
with open(OUT_CSV, 'w', newline='', encoding='utf-8') as cf:
    fieldnames = ['instrument','decision','lots','entry','tp1','tp2','sl','delta_tp1_points','delta_tp2_points','jpy_per_lot_tp1','jpy_per_lot_tp2']
    writer = csv.DictWriter(cf, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

# write JSON
with open(OUT_JSON, 'w', encoding='utf-8') as jf:
    json.dump({'run_id': j.get('run_id'), 'analysis': rows}, jf, ensure_ascii=False, indent=2)

# print a short summary
for r in rows:
    print(f"{r['instrument']}: decision={r['decision']} entry={r['entry']} TP1={r['tp1']} TP2={r['tp2']} SL={r['sl']} Δ(TP1)={r['delta_tp1_points']} pts -> {r['jpy_per_lot_tp1']} JPY/lot")

print('\nSaved analysis to', OUT_CSV, 'and', OUT_JSON)
