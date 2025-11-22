#!/usr/bin/env python3
"""Normalize CSV filenames in ./data by creating safe symlinks with expected 60/240 tokens.

This script will NOT overwrite existing files. It will create a symlink next to the original
file with replacements:
 - '241' -> '240'
 - '_241' -> '_240'
 - '31'  -> '60'   (only when appears as separate token like '_31' or '*_31*')

This is a non-destructive helper to allow existing CSVs to match glob patterns used by
`cfd3_portfolio_update_v2.py`.
"""
import os
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./data")

CHANGES = [
    ("241", "240"),
    ("_241", "_240"),
    ("_31", "_60"),
    ("-31", "-60"),
]

def propose_new_name(p: Path) -> Path | None:
    name = p.name
    new = name
    for a, b in CHANGES:
        if a in new:
            new = new.replace(a, b)
    if new == name:
        return None
    return p.with_name(new)

def main():
    created = []
    skipped = []
    for p in ROOT.rglob("*.csv"):
        newp = propose_new_name(p)
        if not newp:
            continue
        if newp.exists():
            skipped.append((p, newp, "exists"))
            continue
        try:
            # create relative symlink if possible
            rel = os.path.relpath(p, start=newp.parent)
            newp.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(rel, newp)
            created.append((p, newp))
        except Exception as e:
            skipped.append((p, newp, str(e)))

    print("Created symlinks:")
    for src, dst in created:
        print(f"  {dst} -> {src}")
    if skipped:
        print("Skipped:")
        for src, dst, reason in skipped:
            print(f"  {dst} (from {src}) : {reason}")

if __name__ == '__main__':
    main()
