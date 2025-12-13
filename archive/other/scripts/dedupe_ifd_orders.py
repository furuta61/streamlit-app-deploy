#!/usr/bin/env python3
"""Remove duplicate IFD entries in output/ifd_orders.jsonl.

Dedup rule: keep the most recent occurrence for a given key.
Key is (instrument, entry_price, ifd_legs JSON normalized).

Creates a backup of the original file before overwriting.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
import shutil

ROOT = Path(__file__).resolve().parent.parent
IFD_FILE = ROOT / 'output' / 'ifd_orders.jsonl'


def load_lines(path: Path):
    if not path.exists():
        return []
    with open(path, 'r', encoding='utf-8') as f:
        lines = [line.rstrip('\n') for line in f if line.strip()]
    return lines


def parse_json_safe(line: str):
    try:
        return json.loads(line)
    except Exception:
        return None


def make_key(obj: dict):
    instr = obj.get('instrument') or obj.get('symbol')
    entry = obj.get('entry_price') or obj.get('entry_price')
    legs = obj.get('ifd_legs') or obj.get('ifd_legs')
    legs_json = json.dumps(legs, sort_keys=True, ensure_ascii=False) if legs is not None else ''
    return (instr, float(entry) if entry is not None else None, legs_json)


def backup(path: Path) -> Path:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = path.with_suffix(path.suffix + f'.dedupe.bak_{ts}')
    shutil.copy2(path, dest)
    return dest


def dedupe(lines: list[str]):
    parsed = []
    for line in lines:
        obj = parse_json_safe(line)
        parsed.append((line, obj))

    # iterate reversed to keep the most recent occurrence
    seen = set()
    out = []
    for line, obj in reversed(parsed):
        if obj is None:
            # keep unparsable lines
            out.append(line)
            continue
        key = make_key(obj)
        if key in seen:
            # skip duplicate
            continue
        seen.add(key)
        out.append(line)

    out.reverse()
    return out


def write_lines(path: Path, lines: list[str]):
    with open(path, 'w', encoding='utf-8') as f:
        for l in lines:
            f.write(l.rstrip('\n') + '\n')


def main():
    if not IFD_FILE.exists():
        print(f"No IFD file at {IFD_FILE}")
        return
    lines = load_lines(IFD_FILE)
    print(f"Loaded {len(lines)} lines from {IFD_FILE}")
    new_lines = dedupe(lines)
    print(f"Reduced to {len(new_lines)} lines after dedupe")
    b = backup(IFD_FILE)
    print(f"Backup created: {b}")
    write_lines(IFD_FILE, new_lines)
    print(f"Wrote deduped IFD file: {IFD_FILE}")


if __name__ == '__main__':
    main()
