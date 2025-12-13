#!/usr/bin/env python3
"""Scale IFD proposals to broker (GMO) displayed units for all instruments.

Behaviour:
- For each order in `output/ifd_proposals.json` attempt to read environment variables
  `BROKER_SCALE_<INSTR>` or `BROKER_PRICE_<INSTR>` (e.g. BROKER_PRICE_US30=47472.3).
- If present, compute scale (either use BROKER_SCALE_* directly, or scale = BROKER_PRICE_<INSTR> / our_entry).
- Apply per-instrument scaling to entry/tp/sl and write `output/ifd_proposals_gmo_scaled_all.json`.
- Backup original `output/ifd_proposals.json` and replace it with the scaled file (timestamped backup).

Set environment variables like:
  BROKER_PRICE_US30=47472.3
  BROKER_SCALE_US30=1.376008695652
"""
import json
import os
import time
import logging
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IFD_FP = ROOT / 'output' / 'ifd_proposals.json'
OUT_FP = ROOT / 'output' / 'ifd_proposals_gmo_scaled_all.json'
LOG_FP = ROOT / 'output' / 'scale_guard.log'
HISTORY_FP = ROOT / 'output' / 'scale_history.json'

# Guard defaults (can be overridden by env)
DEFAULT_MIN_SCALE = float(os.getenv('SCALE_MIN', '0.5'))
DEFAULT_MAX_SCALE = float(os.getenv('SCALE_MAX', '1.5'))
# absolute diff thresholds per-instrument (broker_price - our_entry) absolute value
ABS_DIFF_THRESHOLDS = {
    'XAUUSD': float(os.getenv('ABS_DIFF_XAUUSD', '1000')),  # gold: 1000 units
    'JP225': float(os.getenv('ABS_DIFF_JP225', '2000')),
    'NAS100': float(os.getenv('ABS_DIFF_NAS100', '2000')),
    'US30': float(os.getenv('ABS_DIFF_US30', '5000')),
    'COPPER': float(os.getenv('ABS_DIFF_COPPER', '1.0')),
}

# setup logging to file
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')


def env_key_for(instr, kind='PRICE'):
    # normalize instrument to env var (alphanumeric, underscores)
    key = ''.join(ch if ch.isalnum() else '_' for ch in instr.upper())
    return f'BROKER_{kind}_{key}'


def get_scale_for_instrument(instr, our_entry):
    # try explicit scale first
    scale_key = env_key_for(instr, 'SCALE')
    price_key = env_key_for(instr, 'PRICE')
    scale_env = os.getenv(scale_key)
    broker_price = os.getenv(price_key)
    if scale_env:
        try:
            return float(scale_env), f'env:{scale_key}', None
        except Exception:
            pass
    if broker_price:
        try:
            bp = float(broker_price)
            return float(bp) / float(our_entry), f'env:{price_key}({bp})', bp
        except Exception:
            pass
    return None, None, None


def round_price(v):
    # keep previous behaviour: if integer-like -> int, else round to 4 decimals
    if float(v).is_integer():
        return int(round(v))
    return float(round(v, 4))


def check_scale_validity(instr, scale, our_entry, broker_price=None):
    """Return (ok:bool, reason:str). Check against ratio and absolute diff guards."""
    min_s = float(os.getenv('SCALE_MIN', DEFAULT_MIN_SCALE))
    max_s = float(os.getenv('SCALE_MAX', DEFAULT_MAX_SCALE))
    if scale < min_s or scale > max_s:
        return False, f'scale {scale:.4f} outside allowed range [{min_s},{max_s}]'
    # if broker_price provided, check absolute diff
    if broker_price is not None:
        try:
            diff = abs(float(broker_price) - float(our_entry))
            thr = ABS_DIFF_THRESHOLDS.get(instr, float(os.getenv('ABS_DIFF_DEFAULT', '1000000')))
            if diff > thr:
                return False, f'absolute diff {diff} > threshold {thr}'
        except Exception:
            pass
    return True, 'ok'


def append_history(record: dict):
    try:
        HISTORY_FP.parent.mkdir(parents=True, exist_ok=True)
        hist = []
        if HISTORY_FP.exists():
            with open(HISTORY_FP, 'r', encoding='utf-8') as hf:
                try:
                    hist = json.load(hf)
                except Exception:
                    hist = []
        hist.append(record)
        with open(HISTORY_FP, 'w', encoding='utf-8') as hf:
            json.dump(hist, hf, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception('Failed to append to history')


def main():
    if not IFD_FP.exists():
        print('Missing', IFD_FP)
        raise SystemExit(1)

    with open(IFD_FP, 'r', encoding='utf-8') as f:
        j = json.load(f)

    orders = j.get('orders', [])
    new_orders = []
    applied = {}

    for o in orders:
        instr = o.get('instrument')
        entry = o.get('entry_price')
        try:
            our_entry = float(entry)
        except Exception:
            new_orders.append(o)
            continue
        scale_info, src, broker_price = get_scale_for_instrument(instr, our_entry)
        if scale_info is None:
            # no env override for this instrument; keep as-is
            new_orders.append(o)
            continue

        scale = float(scale_info)
        ok, reason = check_scale_validity(instr, scale, our_entry, broker_price)
        if not ok:
            # log and skip applying this scale for safety
            msg = f'SKIPPING scale for {instr}: {reason} via {src}'
            print(msg)
            try:
                with open(LOG_FP, 'a', encoding='utf-8') as lf:
                    lf.write(f"{datetime.utcnow().isoformat()}Z\t{msg}\n")
            except Exception:
                pass
            # keep original order unchanged
            new_orders.append(o)
            # append history note
            append_history({'time': datetime.utcnow().isoformat() + 'Z', 'instrument': instr, 'action': 'skip', 'reason': reason, 'scale': scale, 'src': src})
            continue

        print(f'Applying scale {scale:.12f} to {instr} (our entry {our_entry}) via {src}')

        no = json.loads(json.dumps(o))
        ep = float(no.get('entry_price')) * scale
        no['entry_price'] = round_price(ep)
        for leg in no.get('ifd_legs', []):
            oco = leg.get('oco', {})
            tp = oco.get('take_profit', {}).get('price')
            sl = oco.get('stop_loss', {}).get('price')
            if tp is not None and tp != '':
                try:
                    ntp = float(tp) * scale
                    oco['take_profit']['price'] = round_price(ntp)
                except Exception:
                    pass
            if sl is not None and sl != '':
                try:
                    nsl = float(sl) * scale
                    oco['stop_loss']['price'] = round_price(nsl)
                except Exception:
                    pass

        new_orders.append(no)
        applied[instr] = {'scale': scale, 'src': src}

    out = {'run_id': j.get('run_id', '') + '_gmo_scaled_all', 'orders': new_orders}

    # write scaled output
    OUT_FP.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FP, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # backup and replace main proposals
    ts = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    backup_fp = IFD_FP.parent / f"ifd_proposals.json.bak_before_gmo_scaled_all_{ts}"
    IFD_FP.replace(backup_fp)
    # move new file into place
    OUT_FP.rename(IFD_FP)

    print('Wrote scaled proposals to', IFD_FP)
    if applied:
        print('Applied scales for:', applied)
    else:
        print('No scales applied (no BROKER_SCALE_* or BROKER_PRICE_* found)')


if __name__ == '__main__':
    main()

