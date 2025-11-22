#!/usr/bin/env python3
import json
import os

ROOT = os.path.dirname(os.path.dirname(__file__))
IFD_FP = os.path.join(ROOT, 'output', 'ifd_proposals.json')
ANALYSIS_FP = os.path.join(ROOT, 'output', 'ifd_analysis.json')
ENTRY_FP = os.path.join(ROOT, 'output', 'entry_result.json')
OUT_TXT = os.path.join(ROOT, 'output', 'ifd_human_readable.txt')

# load files if present
if os.path.exists(IFD_FP):
    with open(IFD_FP, 'r', encoding='utf-8') as f:
        ifd = json.load(f)
else:
    ifd = {'orders': []}

analysis = {}
if os.path.exists(ANALYSIS_FP):
    with open(ANALYSIS_FP, 'r', encoding='utf-8') as f:
        a = json.load(f)
        for it in a.get('analysis', []):
            analysis[it['instrument']] = it

entry_results = {}
if os.path.exists(ENTRY_FP):
    with open(ENTRY_FP, 'r', encoding='utf-8') as f:
        er = json.load(f)
        for r in er.get('results', []) + er.get('orders', []):
            entry_results[r.get('instrument')] = r

lines = []
for o in ifd.get('orders', []):
    inst = o.get('instrument')
    decision = o.get('decision')
    lots = o.get('lots')
    entry = o.get('entry_price')
    # extract tp1/tp2/sl
    legs = o.get('ifd_legs', [])
    tp1 = ''
    tp2 = ''
    sl = ''
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

    # rating lookup: prefer entry_results -> analysis -> fallback
    rating = ''
    er = entry_results.get(inst)
    if er:
        rating = er.get('tech_score') or er.get('signal_rating') or ''
    else:
        a = analysis.get(inst)
        if a:
            # analysis entries store delta and jpy; no rating; skip
            rating = a.get('signal_rating') or ''

    # direction: assume buy if TP > entry, sell if TP < entry
    direction = ''
    try:
        if tp1 != '' and float(tp1) > float(entry):
            direction = 'buy'
        elif tp1 != '' and float(tp1) < float(entry):
            direction = 'sell'
        else:
            direction = 'hold'
    except Exception:
        direction = ''

    # formatting: keep decimal precision as in analysis if available
    an = analysis.get(inst)
    def fmt_val(v):
        if v == '':
            return ''
        # if analysis present, use its formatting strings
        if an:
            if inst in an and False:
                pass
        # otherwise print as-is, trimming trailing zeros
        if isinstance(v, float) or isinstance(v, int):
            s = ('{:.4f}'.format(v)).rstrip('0').rstrip('.')
            return s
        return str(v)

    if decision is None:
        decision = ''

    if decision.upper() == 'WAIT' or (decision == '' and lots == 0):
        # special WAIT line
        cur = ''
        if an:
            cur = an.get('entry') or ''
        else:
            cur = entry
        line = f"判定: {decision} (signal_rating={rating}) 方向: {direction} 現値（表示）: {fmt_val(cur)} ロット: {lots} 備考: IFDなし"
    else:
        line = f"判定: {decision} (signal_rating={rating}) 方向: {direction} エントリー (指値): {fmt_val(entry)} TP1: {fmt_val(tp1)}, TP2: {fmt_val(tp2)} SL: {fmt_val(sl)} ロット: {lots} {inst}"

    lines.append(line)

# write out
with open(OUT_TXT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

# print
print('\n'.join(lines))
print('\nSaved to', OUT_TXT)
