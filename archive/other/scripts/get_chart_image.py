#!/usr/bin/env python3
"""
get_chart_image.py

Fetch recent OHLC data via yfinance and save a PNG chart (matplotlib).
Useful for visual inspection or feeding to screenshot-based GPT analysis.
"""
import argparse
from pathlib import Path
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import datetime as dt

OUT = Path('output')
OUT.mkdir(exist_ok=True)

def save_chart(symbol: str, days: int = 30, filename: str = None):
    end = dt.datetime.now()
    start = end - dt.timedelta(days=days)
    tk = yf.Ticker(symbol)
    hist = tk.history(start=start.date(), end=end.date(), interval='1d')
    if hist is None or hist.empty:
        raise RuntimeError('No data')

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(hist.index, hist['Close'], label='Close')
    ax.fill_between(hist.index, hist['Low'], hist['High'], alpha=0.1)
    ax.set_title(f'{symbol} close ({days}d)')
    ax.set_xlabel('Date')
    ax.set_ylabel('Price')
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()

    if not filename:
        filename = OUT / f'chart_{symbol.replace("/","_")}_{dt.datetime.utcnow().strftime("%Y%m%d_%H%M")}.png'
    else:
        filename = Path(filename)

    fig.savefig(filename, bbox_inches='tight', dpi=150)
    plt.close(fig)
    print('Wrote', filename)
    return filename

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--symbol', required=True)
    p.add_argument('--days', type=int, default=30)
    args = p.parse_args()
    save_chart(args.symbol, args.days)

if __name__ == '__main__':
    main()
