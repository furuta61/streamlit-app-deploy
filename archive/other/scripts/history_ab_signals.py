#!/usr/bin/env python3
"""
history_ab_signals.py

簡易履歴A/Bテスト：ETF-only (1321.T) と ensemble_median(1321.T,1330.T) の日次ベースの
シグナル（BUY/SELL/NEUTRAL）を過去 N 日で比較し、シグナル一致率と単純な翌日保有の累積リターンを報告します。

このスクリプトは trend_analyzer のロジックを日次データ向けに簡素化して再実装しています。
目的は「ETF と ensemble の入力差がシグナル／仮想P/L にどの程度影響するか」を素早く評価することです。

使い方:
  ./.venv/bin/python3 scripts/history_ab_signals.py --days 365

注意: これは簡易プロキシ計算です。トレードの実際の注文タイプやTP/SL管理は実装していません。
"""
import argparse
import datetime as dt
import numpy as np
import pandas as pd

import yfinance as yf


def fetch_daily(symbol, start, end):
    tk = yf.Ticker(symbol)
    hist = tk.history(start=start, end=end, interval='1d')
    if hist is None or hist.empty:
        return pd.Series(dtype=float)
    s = hist['Close'].copy()
    s.index = pd.to_datetime(s.index).date
    s.name = symbol
    return s


def compute_signals(series: pd.Series) -> pd.DataFrame:
    """Compute simplified signals (BUY/SELL/NEUTRAL) from daily close series."""
    df = pd.DataFrame({'Close': series}).copy()
    # SMA10 / SMA25
    df['SMA10'] = df['Close'].rolling(window=10, min_periods=5).mean()
    df['SMA25'] = df['Close'].rolling(window=25, min_periods=10).mean()
    # MACD using 12/26 EMA
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    # RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=7).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=7).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))

    # vote logic similar to trend_analyzer
    def decide(row):
        if np.isnan(row['Close']):
            return 'NEUTRAL'
        buy_votes = 0
        sell_votes = 0
        # SMA
        if pd.notna(row['SMA10']) and pd.notna(row['SMA25']):
            if row['Close'] > row['SMA10'] > row['SMA25']:
                buy_votes += 2
            elif row['Close'] < row['SMA10'] < row['SMA25']:
                sell_votes += 2
        # MACD
        if pd.notna(row['MACD']) and pd.notna(row['Signal']):
            if row['MACD'] > row['Signal'] and row['MACD'] > 0:
                buy_votes += 2
            elif row['MACD'] < row['Signal'] and row['MACD'] < 0:
                sell_votes += 2
        # RSI
        if pd.notna(row['RSI']):
            if row['RSI'] < 30:
                buy_votes += 1
            elif row['RSI'] > 70:
                sell_votes += 1

        if buy_votes == 0 and sell_votes == 0:
            return 'NEUTRAL'
        if buy_votes > sell_votes:
            return 'BUY'
        if sell_votes > buy_votes:
            return 'SELL'
        return 'NEUTRAL'

    df['signal'] = df.apply(decide, axis=1)
    return df


def simulate_returns(series: pd.Series, signals: pd.Series):
    """Simple next-day holding return simulation: for BUY, return = (next_close - entry)/entry; SELL treated as short.
    Returns cumulative return (compounded) and count of signals.
    """
    df = pd.DataFrame({'close': series}).join(signals.rename('signal'))
    df = df.dropna(subset=['close'])
    returns = []
    for i in range(len(df) - 1):
        sig = df['signal'].iloc[i]
        if sig not in ('BUY', 'SELL'):
            continue
        entry = df['close'].iloc[i]
        nxt = df['close'].iloc[i + 1]
        if entry == 0:
            continue
        if sig == 'BUY':
            r = (nxt - entry) / entry
        else:
            # short
            r = (entry - nxt) / entry
        returns.append(r)
    # compound simple returns
    cum = 1.0
    for r in returns:
        cum *= (1.0 + r)
    cum_return = cum - 1.0
    return {'count': len(returns), 'cum_return': cum_return, 'mean_return': np.mean(returns) if returns else 0.0}


def run(days: int = 365):
    end = dt.datetime.now().date()
    start = end - dt.timedelta(days=days + 50)  # extra for lookbacks

    s1 = fetch_daily('1321.T', start, end)
    s2 = fetch_daily('1330.T', start, end)
    idx = fetch_daily('^N225', start, end)

    if s1.empty or idx.empty:
        print('Insufficient data; abort')
        return 2

    # align
    combined = pd.concat([s1, s2, idx], axis=1, join='inner').dropna()
    combined.columns = ['s1', 's2', 'idx']

    # compute series for ETF-only and ensemble-median
    series_etf = combined['s1']
    series_ens = combined[['s1', 's2']].median(axis=1)

    df_etf = compute_signals(series_etf)
    df_ens = compute_signals(series_ens)

    # restrict to last `days` available
    df_etf = df_etf.tail(days)
    df_ens = df_ens.tail(days)

    # compare signals
    merged = pd.concat([df_etf['signal'], df_ens['signal']], axis=1, keys=['etf','ens']).dropna()
    merged = merged[~merged.index.duplicated()]
    total = len(merged)
    agree = (merged['etf'] == merged['ens']).sum()
    agree_pct = agree / total * 100.0 if total else 0.0

    # simulate returns
    ret_etf = simulate_returns(series_etf.loc[merged.index], merged['etf'])
    ret_ens = simulate_returns(series_ens.loc[merged.index], merged['ens'])

    print('Days compared:', total)
    print('Agreement count:', agree, f'({agree_pct:.2f}%)')
    print('\nETF-only signals: count={count}, cum_return={cum:.4%}, mean_ret={mean:.4%}'.format(count=ret_etf['count'], cum=ret_etf['cum_return'], mean=ret_etf['mean_return']))
    print('Ensemble signals: count={count}, cum_return={cum:.4%}, mean_ret={mean:.4%}'.format(count=ret_ens['count'], cum=ret_ens['cum_return'], mean=ret_ens['mean_return']))

    # show breakdown
    print('\nSignal distribution (ETF-only):')
    print(df_etf['signal'].value_counts())
    print('\nSignal distribution (Ensemble):')
    print(df_ens['signal'].value_counts())

    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--days', type=int, default=365)
    args = p.parse_args()
    return run(args.days)


if __name__ == '__main__':
    main()
