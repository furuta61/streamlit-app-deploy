#!/usr/bin/env python3
from pathlib import Path
import pandas as pd
import sys
sys.path.insert(0, '/Users/otomi/Desktop/CFD3_AutoSystem')
from market_data_fetch import fetch_market_data

P = Path('/tmp/events_test5.csv')
if not P.exists():
    print('MISSING /tmp/events_test5.csv')
    raise SystemExit(1)

events = pd.read_csv(P)
if 'date' in events.columns:
    events['date'] = pd.to_datetime(events['date'])
elif 'datetime' in events.columns:
    events['date'] = pd.to_datetime(events['datetime'])
else:
    # try to find ISO-like column
    for c in events.columns:
        try:
            events[c] = pd.to_datetime(events[c])
            events = events.rename(columns={c: 'date'})
            break
        except Exception:
            continue
    if 'date' not in events.columns:
        events['date'] = pd.to_datetime('now')

market = fetch_market_data(days=30)
merged = pd.merge_asof(events.sort_values('date'), market.sort_values('date'), on='date', direction='backward')
print('--- merged head ---')
print(merged.head().to_string())
out = Path('/tmp/events_merged_test5.csv')
merged.to_csv(out, index=False, encoding='utf-8-sig')
print('wrote', out)
