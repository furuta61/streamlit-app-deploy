#!/usr/bin/env python3
import os
import sys
# Ensure repo root is on sys.path so we can import mygpt_strategy when running from scripts/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from mygpt_strategy import generate_ifd_order

symbols = [
    ("JP225", 51200.0),
    ("NQ100", 16000.0),
    ("XAUUSD", 2000.0),
    ("XAGUSD", 25.0),
    ("NGAS", 3.5),
    ("GER40", 16500.0),
]

for sym, price in symbols:
    order = generate_ifd_order(sym, price, 'STRONG_GO', None)
    print('Generated IFD for', sym, '=>', order)
