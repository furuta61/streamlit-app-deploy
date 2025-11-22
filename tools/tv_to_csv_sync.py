#!/usr/bin/env python3
"""tv_to_csv_sync.py

Simple helper: read the latest TradingView webhook log (`output/tradingview.jsonl`),
find the most recent entry for US30 (or common aliases), and update the latest
4h CSV for US30 by replacing the last row's close with the TV price.

This is a pragmatic short-term sync to ensure IFD uses the TV price until a
full pipeline is implemented.
"""
import os
import json
import glob
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
OUT = os.path.join(ROOT, 'output')
DATA = os.path.join(ROOT, 'data')
TV_LOG = os.path.join(OUT, 'tradingview.jsonl')


def find_latest_tv_price_for(symbol_key='US30'):
    if not os.path.exists(TV_LOG):
        return None
    aliases = [symbol_key, 'US30', 'DJI', '^DJI', 'US 30', 'US30USD']
    with open(TV_LOG, 'r', encoding='utf-8') as fh:
        for line in reversed(list(fh)):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            data = entry.get('data') or entry.get('payload') or {}
            # data may be dict with 'symbol' and 'price' keys
            sym = None
            price = None
            if isinstance(data, dict):
                for k in ('symbol', 's', 'ticker'):
                    if k in data:
                        sym = str(data.get(k))
                        break
                for k in ('price', 'p', 'close', 'c'):
                    if k in data:
                        try:
                            price = float(data.get(k))
                            break
                        except Exception:
                            pass
            if sym and any(a.lower() in sym.lower() for a in aliases):
                if price is not None:
                    return price, entry
            # fallback: if no symbol but top-level contains our symbol_key
            if not sym and isinstance(data, dict) and symbol_key in json.dumps(data):
                if price is not None:
                    return price, entry
    return None


def latest_csv_for_symbol(symbol_key, data_dir=DATA):
    # heuristics: try several filename patterns that commonly appear in repo
    pats = [f'*{symbol_key}*240*.csv', f'*{symbol_key}*_240.csv', f'*{symbol_key}*240.csv']
    # common aliases for some symbols
    aliases_map = {
        'US30': ['US30', 'DJI', 'DJIA', 'US 30'],
        'JP225': ['JP225', 'JP225', 'NIKKEI', 'FOREXCOM_JP225', 'JP225_240'],
        'XAUUSD': ['XAUUSD', 'GOLD', 'XAU'],
        'US30USD': ['US30', 'DJI'],
    }
    candidates = []
    # try direct patterns first
    for p in pats:
        candidates.extend(glob.glob(os.path.join(data_dir, p)))
    # if none, try aliases
    if not candidates:
        aliases = aliases_map.get(symbol_key, [symbol_key])
        for a in aliases:
            candidates.extend(glob.glob(os.path.join(data_dir, f'*{a}*240*.csv')))
            candidates.extend(glob.glob(os.path.join(data_dir, f'*{a}*_240.csv')))
    if not candidates:
        # try any 240 csv in data dir (last-resort)
        candidates = glob.glob(os.path.join(data_dir, '**/*240*.csv'), recursive=True)
    if not candidates:
        return None
    candidates.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return candidates[0]


def backup_file(fp):
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = fp + f'.bak_{ts}'
    shutil.copy2(fp, bak)
    return bak


def update_last_close(csv_fp, new_close):
    # read all lines, replace last non-empty data line's close (5th column)
    with open(csv_fp, 'r', encoding='utf-8') as fh:
        lines = fh.read().splitlines()
    if not lines:
        raise RuntimeError('empty csv')
    # header is first line
    header = lines[0]
    data_lines = lines[1:]
    # find last non-empty line index
    for i in range(len(data_lines) - 1, -1, -1):
        if data_lines[i].strip():
            parts = data_lines[i].split(',')
            if len(parts) < 5:
                raise RuntimeError('unexpected csv format')
            # replace close (5th column, index 4)
            parts[4] = f'{new_close}'
            data_lines[i] = ','.join(parts)
            break
    else:
        raise RuntimeError('no data row found')
    # write back
    with open(csv_fp, 'w', encoding='utf-8') as fh:
        fh.write(header + '\n')
        fh.write('\n'.join(data_lines) + '\n')


def main():
    import sys
    symbol = 'US30'
    if len(sys.argv) > 1:
        symbol = sys.argv[1]
    res = find_latest_tv_price_for(symbol)
    if not res:
        print(f'No TV price found for {symbol} in', TV_LOG)
        return 2
    price, entry = res
    print(f'Found TV price for {symbol}:', price)
    csv_fp = latest_csv_for_symbol(symbol)
    if not csv_fp:
        print(f'No {symbol} 240 CSV found under', DATA)
        return 3
    print('Updating CSV:', csv_fp)
    bak = backup_file(csv_fp)
    print('Backup saved to', bak)
    update_last_close(csv_fp, price)
    print('CSV updated. IFD should now pick up the TV price on next run.')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
