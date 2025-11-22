#!/usr/bin/env python3
"""Convert FOREXCOM CSVs that have extra header rows into normalized CSVs with columns:
time,open,high,low,close,volume

This script writes cleaned files into ./data with the same base name (overwriting any symlink at that path).
"""
import csv
from pathlib import Path
import sys

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./data")

pairs = [
    (ROOT / 'JP225' / 'FOREXCOM_JP225_241.csv', ROOT / 'FOREXCOM_JP225_240.csv'),
    (ROOT / 'JP225' / 'FOREXCOM_JP225_31.csv',  ROOT / 'FOREXCOM_JP225_60.csv'),
    (ROOT / 'NAS100' / 'FOREXCOM_NAS100_241.csv', ROOT / 'FOREXCOM_NAS100_240.csv'),
    (ROOT / 'NAS100' / 'FOREXCOM_NAS100_31.csv',  ROOT / 'FOREXCOM_NAS100_60.csv'),
]

def clean(src: Path, dst: Path):
    if not src.exists():
        print(f"source missing: {src}")
        return
    # remove existing dst (symlink or file)
    try:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
    except Exception:
        pass

    with src.open('r', encoding='utf-8', errors='ignore') as f:
        # read lines and detect header row that contains 'datetime' or 'time'
        lines = f.readlines()

    # choose the header row that contains the most known tokens (open/high/low/close/price/time)
    tokens = ('open', 'high', 'low', 'close', 'price', 'time', 'datetime', 'date', 'volume')
    best_i = None
    best_count = -1
    for i, line in enumerate(lines[:6]):
        l = line.lower()
        cnt = sum(1 for t in tokens if t in l)
        if cnt > best_count:
            best_count = cnt
            best_i = i
    # If there is a 'price/close/...' line and a later 'datetime' line, use the price line as header
    idx_price = None
    idx_datetime = None
    for i, line in enumerate(lines[:6]):
        l = line.lower()
        if any(token in l for token in ('price','close','open','high','low')):
            idx_price = i
        if 'datetime' in l:
            idx_datetime = i
    if idx_price is not None and idx_datetime is not None and idx_price < idx_datetime:
        header_row_index = idx_price
    else:
        # If a line explicitly contains 'datetime' prefer that line as header
        found_dt = False
        for i, line in enumerate(lines[:6]):
            if 'datetime' in line.lower():
                header_row_index = i
                found_dt = True
                break
        if not found_dt:
            header_row_index = best_i if best_i is not None else 0

    # Parse all lines and find where actual data rows start (first row whose first token looks like a date)
    all_rows = list(csv.reader(lines))
    data_start = None
    import re
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}")
    for i, r in enumerate(all_rows):
        if not r:
            continue
        if date_re.match(r[0].strip()):
            data_start = i
            break
    if data_start is None:
        print(f"no data rows found in {src}")
        return

    # find header row among lines before data_start (prefer a line containing price/close/open/high/low)
    header_row = None
    for i in range(max(0, data_start-4), data_start):
        row = [c.strip().lower() for c in all_rows[i]]
        if any(tok in ','.join(row) for tok in ('price','close','open','high','low')):
            header_row = row
            break
    if header_row is None:
        # fallback to the row immediately before data_start
        header_row = [c.strip().lower() for c in all_rows[data_start-1]]

    # ensure header includes time as first column
    if not any(k in ','.join(header_row) for k in ('time','datetime','date')):
        header_row = ['time'] + header_row

    # build mapping
    mapping = {}
    for idx, col in enumerate(header_row):
        if 'date' in col or 'time' in col:
            mapping['time'] = idx
        elif col == 'open':
            mapping['open'] = idx
        elif col == 'high':
            mapping['high'] = idx
        elif col == 'low':
            mapping['low'] = idx
        elif col in ('close','price'):
            mapping['close'] = idx
        elif 'vol' in col:
            mapping['volume'] = idx

    needed = ['time','open','high','low','close']
    if not all(k in mapping for k in needed):
        print(f"cannot map columns for {src}. detected: {mapping}")
        return

    # write cleaned CSV using rows from data_start onward
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open('w', encoding='utf-8', newline='') as fout:
        writer = csv.writer(fout)
        writer.writerow(['time','open','high','low','close','volume'])
        for row in all_rows[data_start:]:
            # pad row if shorter than mapping indexes
            if len(row) <= max(mapping.values()):
                # try to skip malformed rows
                continue
            try:
                out = [row[mapping['time']], row[mapping['open']], row[mapping['high']], row[mapping['low']], row[mapping['close']], row[mapping.get('volume','')]]
            except Exception:
                continue
            writer.writerow(out)
    print(f"wrote cleaned {dst}")

def main():
    for src, dst in pairs:
        clean(src, dst)

if __name__ == '__main__':
    main()
