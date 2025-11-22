#!/usr/bin/env python3
import json, os
ROOT = os.path.dirname(os.path.dirname(__file__))
TV_FP = os.path.join(ROOT, 'output', 'tradingview.jsonl')
IFD_FP = os.path.join(ROOT, 'output', 'ifd_proposals.json')
OUT_FP = os.path.join(ROOT, 'output', 'ifd_proposals_tv_overridden.json')

# rounding map for decimals (mirror of other scripts)
DECIMALS = {
    'JP225': 0,
    'NAS100': 0,
    'US30': 0,
    'XAUUSD': 2,
    'COPPER': 3,
}

# load latest tv prices/signals
def latest_tv(fp):
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

# load ifd
if not os.path.exists(IFD_FP):
    print('IFD proposals missing:', IFD_FP)
    raise SystemExit(1)

with open(IFD_FP, 'r', encoding='utf-8') as f:
    ifd = json.load(f)

orders = ifd.get('orders', [])
tv = latest_tv(TV_FP)

modified = False
new_orders = []
for o in orders:
    inst = o.get('instrument')
    entry = o.get('entry_price')
    legs = o.get('ifd_legs', [])
    # get tp1
    tp1 = None
    sl = None
    try:
        tp1 = legs[0]['oco']['take_profit']['price']
    except Exception:
        tp1 = None
    try:
        sl = legs[0]['oco']['stop_loss']['price']
    except Exception:
        sl = None

    tvrec = tv.get(inst)
    # attempt to prefer alternate TV keys for gold: 'GOLD', 'XAU' or GC symbol if present
    if inst == 'XAUUSD':
        for alt in ('GOLD', 'XAU'):
            if alt in tv and (tvrec is None or tv.get(alt).get('price') is not None):
                # prefer alt if it has a numeric price
                try:
                    if float(tv.get(alt).get('price')):
                        tvrec = tv.get(alt)
                        break
                except Exception:
                    pass
    # additionally, if tvrec price looks implausible for gold (<3000) but CSV/yf data shows ~4k, prefer CSV
    def read_last_csv_close(path):
        try:
            with open(path, 'r', encoding='utf-8') as cf:
                lines = [l for l in cf if l.strip()]
            if not lines:
                return None
            last = lines[-1].strip().split(',')
            # assume close is 5th column (0-based 4) for CSVs used here
            return float(last[4])
        except Exception:
            return None

    if tvrec and inst == 'XAUUSD':
        try:
            tvprice = float(tvrec.get('price')) if tvrec.get('price') is not None else None
        except Exception:
            tvprice = None
        # check CSV fallback
        csv_gold = read_last_csv_close(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'XAUUSD', 'TVC_GOLD_240.csv'))
        csv_xau = read_last_csv_close(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'XAUUSD_240.csv'))
        # prefer a realistic gold price if tvprice is suspiciously low
        if tvprice is not None and tvprice < 3000:
            if csv_gold and csv_gold > 3000:
                tvrec = {'price': csv_gold, 'signal': tvrec.get('signal'), 'raw': {'source': 'TVC_GOLD_240.csv'}}
            elif csv_xau and csv_xau > 3000:
                tvrec = {'price': csv_xau, 'signal': tvrec.get('signal'), 'raw': {'source': 'XAUUSD_240.csv'}}
    if tvrec and tvrec.get('signal'):
        tvsig = str(tvrec.get('signal')).upper()
        if tvsig == 'STRONG_GO':
            # decide current direction in IFD (based on tp1 vs entry)
            try:
                cur_dir = 'buy' if (tp1 is not None and float(tp1) > float(entry)) else 'sell'
            except Exception:
                cur_dir = None
            # tv direction: if TV has price and signal STRONG_GO, assume buy (user reported buy) unless text indicates sell
            # We'll interpret TV STRONG_GO as buy by default
            tv_dir = 'buy'
            if cur_dir and tv_dir != cur_dir:
                # override: keep TP distances but flip direction to tv_dir and set entry to tv price
                tv_price = tvrec.get('price')
                if tv_price is not None:
                    # compute distance d1 = abs(tp1 - entry)
                    try:
                        d1 = abs(float(tp1) - float(entry)) if tp1 is not None else None
                    except Exception:
                        d1 = None
                    try:
                        d2 = abs(float(legs[1]['oco']['take_profit']['price']) - float(entry)) if len(legs) > 1 and legs[1]['oco'].get('take_profit') else None
                    except Exception:
                        d2 = None
                    try:
                        dsl = abs(float(sl) - float(entry)) if sl is not None else None
                    except Exception:
                        dsl = None

                    # build new leg prices: if tv_dir == buy => tp = tv_price + d, sl = tv_price - dsl
                    new_o = json.loads(json.dumps(o))
                    dec = DECIMALS.get(inst, 2)
                    def rnd(v):
                        if v is None:
                            return None
                        if dec == 0:
                            return int(round(v))
                        return round(v, dec)

                    new_entry = float(tv_price)
                    new_o['entry_price'] = rnd(new_entry)
                    # update legs
                    if d1 is not None:
                        new_tp1 = new_entry + d1
                        new_o['ifd_legs'][0]['oco']['take_profit']['price'] = rnd(new_tp1)
                    if dsl is not None:
                        new_sl = new_entry - dsl
                        new_o['ifd_legs'][0]['oco']['stop_loss']['price'] = rnd(new_sl)
                    # tp2 if present
                    if d2 is not None and len(new_o['ifd_legs']) > 1:
                        new_tp2 = new_entry + d2
                        new_o['ifd_legs'][1]['oco']['take_profit']['price'] = rnd(new_tp2)
                    new_orders.append(new_o)
                    modified = True
                    print(f"Overrode {inst}: entry {entry} -> {new_o['entry_price']}, tp1->{new_o['ifd_legs'][0]['oco']['take_profit']['price']}, sl->{new_o['ifd_legs'][0]['oco']['stop_loss']['price']}")
                    continue
    new_orders.append(o)

out = {'run_id': ifd.get('run_id') + '_tv_override', 'orders': new_orders}
with open(OUT_FP, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print('Wrote overridden proposals to', OUT_FP)
if modified:
    # also write a backup and replace main proposals with overridden
    import shutil, time
    ts = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    bak = os.path.join(ROOT, 'output', f'ifd_proposals.json.bak_before_tv_override_{ts}')
    shutil.copy(IFD_FP, bak)
    shutil.copy(OUT_FP, IFD_FP)
    print('Backed up original to', bak, 'and replaced', IFD_FP)
else:
    print('No changes made')
