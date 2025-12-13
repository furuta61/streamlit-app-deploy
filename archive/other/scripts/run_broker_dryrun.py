#!/usr/bin/env python3
import json
import os

# import the executor
try:
    from app.gmo_order_executor import execute_gmo_order
except Exception as e:
    print('Failed to import execute_gmo_order:', e)
    execute_gmo_order = None

IFD_FP = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'output', 'ifd_proposals.json')

if not os.path.exists(IFD_FP):
    print('IFD proposals not found at', IFD_FP)
    raise SystemExit(1)

with open(IFD_FP, 'r', encoding='utf-8') as f:
    j = json.load(f)

orders = j.get('orders', [])

for o in orders:
    inst = o.get('instrument')
    entry = o.get('entry_price')
    legs = o.get('ifd_legs', [])
    tp = None
    sl = None
    try:
        tp = legs[0]['oco']['take_profit']['price']
    except Exception:
        pass
    try:
        sl = legs[0]['oco']['stop_loss']['price']
    except Exception:
        pass

    ifd_order = {
        'symbol': inst,
        'entry_price': entry,
        'take_profit': tp,
        'stop_loss': sl,
        'lots': o.get('lots')
    }

    print('--- Dry-run for', inst)
    if execute_gmo_order:
        try:
            execute_gmo_order(ifd_order)
        except Exception as e:
            print('Error executing dry-run order for', inst, e)
    else:
        print('execute_gmo_order not available; skipping')

print('Done')
