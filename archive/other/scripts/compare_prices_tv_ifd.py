#!/usr/bin/env python3
import json, os
ROOT = os.path.dirname(os.path.dirname(__file__))
TV_FP = os.path.join(ROOT, 'output', 'tradingview.jsonl')
IFD_FP = os.path.join(ROOT, 'output', 'ifd_proposals.json')

# load latest tv prices (last seen per symbol)

def latest_tv_prices(fp):
    out = {}
    if not os.path.exists(fp):
        return out
    with open(fp, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            data = j.get('data') or {}
            sym = data.get('symbol')
            price = data.get('price')
            signal = data.get('signal')
            if sym:
                out[sym] = {'price': price, 'signal': signal, 'raw': data}
    return out


def ifd_entries(fp):
    out = {}
    if not os.path.exists(fp):
        return out
    with open(fp, 'r', encoding='utf-8') as f:
        j = json.load(f)
    for o in j.get('orders', []):
        inst = o.get('instrument')
        entry = o.get('entry_price')
        out[inst] = entry
    return out

if __name__ == '__main__':
    tv = latest_tv_prices(TV_FP)
    ifd = ifd_entries(IFD_FP)
    print('Symbol | TV_price | TV_signal | IFD_entry | ratio(TV/IFD)')
    for s in sorted(set(list(tv.keys())+list(ifd.keys()))):
        tvp = tv.get(s, {}).get('price')
        tvsig = tv.get(s, {}).get('signal')
        ifd_entry = ifd.get(s)
        ratio = None
        try:
            if tvp is not None and ifd_entry is not None:
                ratio = float(tvp) / float(ifd_entry)
        except Exception:
            ratio = None
        print(f"{s:6} | {str(tvp):>8} | {str(tvsig):>9} | {str(ifd_entry):>10} | {str(round(ratio,6)) if ratio is not None else 'N/A'}")
    
    # highlight large discrepancies
    print('\nLarge discrepancies (ratio <0.5 or >1.5):')
    for s in sorted(set(list(tv.keys())+list(ifd.keys()))):
        tvp = tv.get(s, {}).get('price')
        ifd_entry = ifd.get(s)
        try:
            if tvp is not None and ifd_entry is not None:
                ratio = float(tvp)/float(ifd_entry)
                if ratio < 0.5 or ratio > 1.5:
                    print(f"- {s}: tv={tvp} ifd={ifd_entry} ratio={ratio:.6f}")
        except Exception:
            pass
