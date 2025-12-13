#!/usr/bin/env python3
"""
Simple TP/SL backtester for ETF-only vs Ensemble signals.

Usage:
  ./scripts/backtest_tpsl.py --days 365 --tp 0.005 --sl 0.005 --max_hold 1

This script expects `scripts/history_ab_signals.py` to be present and uses the same
signal-generation rules: it will import the function that generates signals if available,
otherwise it will re-run a simplified signal generator using yfinance closes.

Outputs a short summary comparing cumulative returns,win-rate,mean return per trade.
"""
import argparse
import os
import sys
import json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf

# try to import existing history AB script's signal generator
try:
    from scripts.history_ab_signals import generate_signals_from_series
except Exception:
    generate_signals_from_series = None


def fetch_close_series(symbol, days=365):
    end = datetime.now()
    start = end - timedelta(days=days)
    tk = yf.Ticker(symbol)
    hist = tk.history(start=start.date(), end=end.date(), interval='1d')
    if hist is None or hist.empty:
        return pd.Series(dtype=float)
    s = hist['Close'].copy()
    s.index = pd.to_datetime(s.index).date
    s.name = symbol
    return s


def simple_signal(series):
    # Minimal signal generator: compare 5-day SMA vs 20-day SMA
    df = pd.DataFrame({'price': series})
    df['s5'] = df['price'].rolling(5).mean()
    df['s20'] = df['price'].rolling(20).mean()
    def f(row):
        if pd.isna(row['s5']) or pd.isna(row['s20']):
            return 'NEUTRAL'
        if row['s5'] > row['s20'] * 1.001:
            return 'BUY'
        if row['s5'] < row['s20'] * 0.999:
            return 'SELL'
        return 'NEUTRAL'
    return df.apply(f, axis=1)


def backtest_trades(price_series, signals, tp=0.005, sl=0.005, max_hold_days=1):
    # price_series: pd.Series indexed by date (date objects)
    # signals: pd.Series aligned with price_series index with 'BUY'/'SELL'/'NEUTRAL'
    trades = []
    dates = list(price_series.index)
    for i, d in enumerate(dates):
        sig = signals.get(d, 'NEUTRAL')
        if sig not in ('BUY', 'SELL'):
            continue
        entry_price = price_series.loc[d]
        # look forward up to max_hold_days to see if tp/sl hit
        exit_price = None
        exit_date = None
        direction = 1 if sig == 'BUY' else -1
        for h in range(1, max_hold_days+1):
            if i+h >= len(dates):
                break
            p = price_series.loc[dates[i+h]]
            ret = (p - entry_price) / entry_price * direction
            if ret >= tp:
                exit_price = p
                exit_date = dates[i+h]
                result = tp
                break
            if ret <= -sl:
                exit_price = p
                exit_date = dates[i+h]
                result = -sl
                break
        if exit_price is None:
            # exit at last available within horizon
            if i+max_hold_days < len(dates):
                exit_price = price_series.loc[dates[i+max_hold_days]]
                exit_date = dates[i+max_hold_days]
                result = (exit_price - entry_price) / entry_price * direction
            else:
                # can't exit, skip
                continue
        trades.append({'entry_date': d, 'exit_date': exit_date, 'entry': entry_price, 'exit': exit_price, 'direction': sig, 'return': result})
    return pd.DataFrame(trades)


def summarize_trades(df_trades):
    if df_trades.empty:
        return {'n':0,'cum_ret':0.0,'mean':0.0,'win_rate':0.0}
    n = len(df_trades)
    cum = (1 + df_trades['return']).prod() - 1
    mean = df_trades['return'].mean()
    win = (df_trades['return'] > 0).sum() / n
    return {'n': n, 'cum_ret': float(cum), 'mean': float(mean), 'win_rate': float(win)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--days', type=int, default=365)
    p.add_argument('--tp', type=float, default=0.005)
    p.add_argument('--sl', type=float, default=0.005)
    p.add_argument('--max_hold', type=int, default=1)
    p.add_argument('--etf', type=str, default='1321.T')
    p.add_argument('--etf2', type=str, default='1330.T')
    args = p.parse_args()

    s1 = fetch_close_series(args.etf, days=args.days)
    s2 = fetch_close_series(args.etf2, days=args.days)
    idx = fetch_close_series('^N225', days=args.days)

    # Align dates
    df = pd.concat([s1, s2, idx], axis=1, join='inner').dropna()
    df.columns = [args.etf, args.etf2, '^N225']

    # Signals
    sig_etf = simple_signal(df[args.etf])
    sig_ens_median = simple_signal(df[[args.etf, args.etf2]].median(axis=1))

    # Backtest
    trades_etf = backtest_trades(df[args.etf], sig_etf, tp=args.tp, sl=args.sl, max_hold_days=args.max_hold)
    trades_ens = backtest_trades(df[[args.etf, args.etf2]].median(axis=1), sig_ens_median, tp=args.tp, sl=args.sl, max_hold_days=args.max_hold)

    sum_etf = summarize_trades(trades_etf)
    sum_ens = summarize_trades(trades_ens)

    out = {'params': vars(args), 'etf_trades_summary': sum_etf, 'ens_trades_summary': sum_ens}
    print(json.dumps(out, indent=2, ensure_ascii=False))

    # also print simple CSV of trades for manual inspection
    if not trades_etf.empty:
        trades_etf.to_csv('output/backtest_etf_trades.csv', index=False, encoding='utf-8-sig')
    if not trades_ens.empty:
        trades_ens.to_csv('output/backtest_ens_trades.csv', index=False, encoding='utf-8-sig')

if __name__ == '__main__':
    main()
