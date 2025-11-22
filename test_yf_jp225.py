#!/usr/bin/env python3
import pandas as pd
import yfinance as yf

sym = "^N225"
df = yf.download(sym, period="14d", interval="30m", progress=False, auto_adjust=True)

print("type(df.columns):", type(df.columns))
print("columns:", df.columns)

if isinstance(df.columns, pd.MultiIndex):
    print("MultiIndex levels:", df.columns.levels)

print("head():")
print(df.head())
