#!/usr/bin/env python3
import json, os
ROOT = os.path.dirname(os.path.dirname(__file__))
TV_FP = os.path.join(ROOT, 'output', 'tradingview.jsonl')
IFD_FP = os.path.join(ROOT, 'output', 'ifd_proposals.json')

def latest_tv_signals(fp):
    sig = {}
    if not os.path.exists(fp):
        return sig
    with open(fp, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            data = j.get('data') or j.get('payload') or {}
            symbol = data.get('symbol')
            # price may be under price
            signal = data.get('signal') or data.get('text') or None
            if symbol:
                sig[symbol] = {'signal': signal, 'raw': data}
    return sig


def ifd_decisions(fp):
    out = {}
    if not os.path.exists(fp):
        return out
    with open(fp, 'r', encoding='utf-8') as f:
        j = json.load(f)
    for o in j.get('orders', []):
        inst = o.get('instrument')
        dec = o.get('decision')
        out[inst] = dec
    return out

if __name__ == '__main__':
    tv = latest_tv_signals(TV_FP)
    ifd = ifd_decisions(IFD_FP)
    print('Latest TradingView signals (symbol: signal)')
    for s,v in sorted(tv.items()):
        print(f"{s}: {v.get('signal')}")
    print('\nIFD decisions (symbol: decision)')
    for s,v in sorted(ifd.items()):
        print(f"{s}: {v}")

    print('\nDisagreements (TV != IFD)')
    for s in sorted(set(list(tv.keys())+list(ifd.keys()))):
        tvsig = tv.get(s, {}).get('signal')
        ifddec = ifd.get(s)
        # normalize simple values
        def norm(x):
            if x is None:
                return None
            return str(x).upper()
        if norm(tvsig) and norm(ifddec) and norm(tvsig) != norm(ifddec):
            print(f"{s}: TV={tvsig}  IFD={ifddec}")
    
    # list instruments where TV exists but IFD missing and vice versa
    missing_ifd = [s for s in tv.keys() if s not in ifd]
    missing_tv = [s for s in ifd.keys() if s not in tv]
    if missing_ifd:
        print('\nSymbols present in TV but missing in IFD:', missing_ifd)
    if missing_tv:
        print('\nSymbols present in IFD but missing in TV:', missing_tv)
