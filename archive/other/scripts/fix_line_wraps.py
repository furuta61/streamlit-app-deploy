#!/usr/bin/env python3
"""Fix CSV files where rows have been wrapped across lines.

Behavior:
- For each source file under data/* matching FOREXCOM_*_241.csv and *_31.csv,
  read lines and join lines where a line does NOT start with a date (YYYY-)
  to the previous line, inserting a single space between.
- Then split by comma to fields and write cleaned CSV to top-level files:
  data/FOREXCOM_<SYM>_240.csv and data/FOREXCOM_<SYM>_60.csv

This is non-destructive for source files; cleaned files are written/overwritten.
"""
import re
from pathlib import Path
import sys

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./data")

date_re = re.compile(r"^\s*\d{4}-\d{2}-\d{2}")

def join_lines(lines):
    out = []
    buf = None
    for raw in lines:
        line = raw.rstrip('\n').rstrip('\r')
        if date_re.match(line):
            # new record
            if buf is not None:
                out.append(buf)
            buf = line
        else:
            if buf is None:
                # unexpected, start buffer
                buf = line
            else:
                # append continuation with a comma if no comma at join boundary
                # but safer to just append space
                buf = buf + ' ' + line.strip()
    if buf is not None:
        out.append(buf)
    return out

def clean_and_write(src: Path, dst: Path):
    text = src.read_text(encoding='utf-8', errors='ignore')
    lines = text.splitlines()
    joined = join_lines(lines)
    # parse joined lines into CSV fields
    rows = []
    for j in joined:
        # split by comma
        parts = [p.strip() for p in j.split(',')]
        # remove empty trailing elements
        # sometimes there are stray empty at end
        # require at least 6 fields (time,close,high,low,open,volume) or similar
        if len(parts) < 6:
            # try to salvage: collapse spaces and split
            parts = [p for p in re.split(r'\s*,\s*', j) if p]
        if len(parts) >= 6:
            # Many FOREXCOM use order: datetime,close,high,low,open,volume OR Price,Close,High,Low,Open,Volume
            rows.append(parts)
        else:
            # skip malformed
            continue

    if not rows:
        print(f"no usable rows for {src}")
        return

    # Determine mapping: find which column looks like ISO date
    headerless = False
    first = rows[0]
    # If first row's first field contains letters like 'Price' or 'Ticker', skip header rows
    if any(re.search(r'[A-Za-z]', x) for x in first[:2]):
        # remove initial header-like rows
        # find first row where field0 matches date pattern
        data_start = None
        for i, r in enumerate(rows):
            if date_re.match(r[0]):
                data_start = i
                break
        if data_start is None:
            print(f"no data rows found in {src}")
            return
        rows = rows[data_start:]
        headerless = True

    # Now assume rows are [time,close,high,low,open,volume] or [time,open,high,low,close,volume]
    cleaned = []
    for r in rows:
        # try common patterns
        if date_re.match(r[0]):
            # normalize to time,open,high,low,close,volume
            if len(r) >= 6:
                # detect if r[1] looks like close (could be close or open)
                # Heuristic: if r[1] is much larger than r[4] maybe it's close; we'll try both orders
                try:
                    v1 = float(r[1])
                    v4 = float(r[4]) if len(r) > 4 else None
                except Exception:
                    v1 = v4 = None
                # if r contains 'price' header originally, ordering might be Price,Close,High,Low,Open,Volume
                # We'll detect by comparing indices: prefer order datetime,open,high,low,close,volume if values make sense
                if v1 is not None and v4 is not None:
                    # if v1 approx equals v4 sometimes, fallback
                    # We'll assume format datetime,close,high,low,open,volume (observed in files)
                    # But our target is time,open,high,low,close,volume
                    # Map accordingly: if original seems (datetime,close,high,low,open,volume)
                    open_v = r[4]
                    close_v = r[1]
                    high_v = r[2]
                    low_v = r[3]
                    vol = r[5] if len(r) > 5 else ''
                    cleaned.append([r[0], open_v, high_v, low_v, close_v, vol])
                else:
                    # fallback: take first 6 as is but reorder to time,open,high,low,close,volume if necessary
                    # if ambiguous, use indices 0,4,2,3,1,5
                    open_v = r[4] if len(r) > 4 else ''
                    high_v = r[2] if len(r) > 2 else ''
                    low_v = r[3] if len(r) > 3 else ''
                    close_v = r[1] if len(r) > 1 else ''
                    vol = r[5] if len(r) > 5 else ''
                    cleaned.append([r[0], open_v, high_v, low_v, close_v, vol])

    # write cleaned to dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open('w', encoding='utf-8', newline='') as f:
        f.write('time,open,high,low,close,volume\n')
        for r in cleaned:
            f.write(','.join(map(str, r)) + '\n')
    print(f"wrote {dst} ({len(cleaned)} rows)")

def main():
    # process FOREXCOM files under each symbol folder
    for symdir in sorted(ROOT.glob('*')):
        if not symdir.is_dir():
            continue
        for fname in symdir.glob('FOREXCOM_*_241.csv'):
            # derive symbol token from filename parts
            parts = fname.name.split('_')
            token = parts[1] if len(parts) > 1 else parts[0]
            dst = ROOT / f"FOREXCOM_{token}_240.csv"
            clean_and_write(fname, dst)
        for fname in symdir.glob('FOREXCOM_*_31.csv'):
            parts = fname.name.split('_')
            token = parts[1] if len(parts) > 1 else parts[0]
            dst = ROOT / f"FOREXCOM_{token}_60.csv"
            clean_and_write(fname, dst)

if __name__ == '__main__':
    main()
