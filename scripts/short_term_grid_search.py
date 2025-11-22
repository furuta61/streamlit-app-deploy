#!/usr/bin/env python3
"""
短期トレンドパラメータのグリッド検証スクリプト
簡易バックテスト: 指定銘柄の過去N日について、各(期間,interval,threshold)で
シグナルを生成し、シグナル発生後の1時間リターンを評価する。

使い方:
  ./scripts/short_term_grid_search.py --symbol JP225 --days 90

注意: yfinance の intraday データには制約があります。まずは 15m/5m で試行します。
"""

import argparse
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import numpy as np
import sys


def compute_indicators(df):
    # df must have column 'Close'
    df = df.copy()
    df['SMA10'] = df['Close'].rolling(window=10).mean()
    df['SMA25'] = df['Close'].rolling(window=25).mean()
    exp12 = df['Close'].ewm(span=12, adjust=False).mean()
    exp26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp12 - exp26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df


def generate_signals(df):
    # Return a DataFrame column 'direction' and 'strength' per row using same voting logic
    df = compute_indicators(df)
    directions = []
    strengths = []
    for i in range(len(df)):
        row = df.iloc[i]
        sma_signal = 'NEUTRAL'
        if pd.notna(row['SMA10']) and pd.notna(row['SMA25']):
            if row['Close'] > row['SMA10'] > row['SMA25']:
                sma_signal = 'BUY'
            elif row['Close'] < row['SMA10'] < row['SMA25']:
                sma_signal = 'SELL'

        macd_signal = 'NEUTRAL'
        if pd.notna(row['MACD']) and pd.notna(row['Signal']):
            if row['MACD'] > row['Signal'] and row['MACD'] > 0:
                macd_signal = 'BUY'
            elif row['MACD'] < row['Signal'] and row['MACD'] < 0:
                macd_signal = 'SELL'

        rsi = row['RSI'] if pd.notna(row['RSI']) else 50
        rsi_signal = 'NEUTRAL'
        if rsi > 70:
            rsi_signal = 'SELL'
        elif rsi < 30:
            rsi_signal = 'BUY'

        buy_votes = 0
        sell_votes = 0
        if sma_signal == 'BUY':
            buy_votes += 2
        elif sma_signal == 'SELL':
            sell_votes += 2
        if macd_signal == 'BUY':
            buy_votes += 2
        elif macd_signal == 'SELL':
            sell_votes += 2
        if rsi_signal == 'BUY':
            buy_votes += 1
        elif rsi_signal == 'SELL':
            sell_votes += 1

        # approximate recent price changes
        if i >= 2:
            price_change_1 = (row['Close'] - df.iloc[i-1]['Close']) / df.iloc[i-1]['Close'] * 100
        else:
            price_change_1 = 0
        if i >= 4:
            price_change_4 = (row['Close'] - df.iloc[i-4]['Close']) / df.iloc[i-4]['Close'] * 100
        else:
            price_change_4 = 0
        if price_change_1 < -0.3 and price_change_4 < -0.5:
            sell_votes += 1
        elif price_change_1 > 0.3 and price_change_4 > 0.5:
            buy_votes += 1

        total = buy_votes + sell_votes
        if total == 0:
            directions.append('NEUTRAL')
            strengths.append(0.0)
        elif buy_votes > sell_votes:
            directions.append('BUY')
            strengths.append(buy_votes / total)
        elif sell_votes > buy_votes:
            directions.append('SELL')
            strengths.append(sell_votes / total)
        else:
            directions.append('NEUTRAL')
            strengths.append(0.5)

    df['direction'] = directions
    df['strength'] = strengths
    return df


def fetch_history(logical_symbol, yf_symbol, period_days, interval):
    """Fetch intraday history using yfinance first, then Twelve Data if available and needed.
    Returns a DataFrame with columns ['date','Close'] (date=Timestamp).
    """
    # try yfinance first
    try:
        tk = yf.Ticker(yf_symbol)
        period_str = f"{period_days}d"
        df = tk.history(period=period_str, interval=interval)
        if df is not None and not df.empty:
            df = df.reset_index()
            # ensure 'Close' exists
            if 'Close' not in df.columns:
                for c in df.columns:
                    if pd.api.types.is_numeric_dtype(df[c]):
                        df.rename(columns={c: 'Close'}, inplace=True)
                        break
            if 'Datetime' in df.columns:
                df = df[['Datetime','Close']]
            elif 'Date' in df.columns:
                df = df[['Date','Close']]
            else:
                df = df.rename(columns={df.columns[0]:'date'})[['date','Close']]
            df.rename(columns={df.columns[0]:'date'}, inplace=True)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            # if we got a reasonable number of rows, return
            if len(df) >= 6:
                return df
    except Exception:
        pass

    # If yfinance failed or returned insufficient rows, try Twelve Data when API key present
    import os
    td_key = os.environ.get('TWELVE_API_KEY')
    if not td_key:
        return pd.DataFrame()

    try:
        import twelvedata_fetch as td
    except Exception:
        return pd.DataFrame()

    # map interval strings to Twelve Data style
    int_map = {'15m': '15min', '5m': '5min', '1m': '1min', '1h': '1h'}
    td_interval = int_map.get(interval, interval)

    # estimate outputsize roughly: period_days * (24*60 / interval_minutes)
    try:
        if td_interval.endswith('min'):
            mins = int(td_interval.replace('min',''))
        elif td_interval.endswith('h') or td_interval.endswith('hour'):
            mins = int(td_interval.replace('h','')) * 60
        else:
            mins = 60
    except Exception:
        mins = 60
    outsize = max(50, int(period_days * 24 * 60 / max(1, mins)))

    # candidates: prefer logical symbol mapping inside twelvedata module
    candidates = td.SYMBOL_CANDIDATES.get(logical_symbol, [logical_symbol])
    # try candidates directly via call_twelvedata
    for cand in candidates:
        try:
            data = td.call_twelvedata(cand, td_interval, td.get_api_key(), outputsize=outsize)
            if not data:
                continue
            vals = data.get('values')
            if not vals or not isinstance(vals, list):
                continue
            rows = []
            for v in reversed(vals):
                dt = v.get('datetime') or v.get('timestamp')
                close = v.get('close') or v.get('price') or v.get('value')
                try:
                    close_f = float(close) if close is not None else None
                except Exception:
                    close_f = None
                rows.append({'date': dt, 'Close': close_f})
            df = pd.DataFrame(rows)
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.dropna(subset=['date']).reset_index(drop=True)
            if 'Close' in df.columns:
                return df
        except Exception:
            continue

    return pd.DataFrame()


def run_grid(symbol, yf_symbol, days=90):
    periods = [3,5,7,14]
    intervals = ['15m','5m']
    thresholds = [0.65,0.70,0.75,0.80]
    horizon_minutes = 60

    results = []

    for interval in intervals:
        print(f"\n=== Interval: {interval} ===")
        hist = fetch_history(symbol, yf_symbol, days, interval)
        if hist.empty:
            print(f"No data for {yf_symbol} @ {interval}")
            continue
        # compute indicators once
        df = hist.copy()
        df.rename(columns={'date':'Date'}, inplace=True)
        df.set_index('Date', inplace=True)
        df_ind = generate_signals(df)

        # compute future returns for horizon
        # find number of periods for horizon
        # infer period length in minutes from index
        try:
            freq = (df_ind.index[1] - df_ind.index[0]).total_seconds() / 60
        except Exception:
            freq = 15 if interval=='15m' else 5
        steps = int(max(1, round(horizon_minutes / freq)))
        closes = df_ind['Close'].values

        for per in periods:
            for thr in thresholds:
                # filter signals where enough lookback exists: we already computed
                sig_idx = [i for i in range(len(df_ind)) if df_ind.iloc[i]['strength'] >= thr and df_ind.iloc[i]['direction'] in ('BUY','SELL')]
                wins = 0
                returns = []
                for i in sig_idx:
                    if i + steps >= len(closes):
                        continue
                    future = closes[i+steps]
                    cur = closes[i]
                    fut_ret = (future - cur) / cur
                    returns.append(fut_ret)
                    dirn = df_ind.iloc[i]['direction']
                    if dirn == 'BUY' and fut_ret > 0:
                        wins += 1
                    if dirn == 'SELL' and fut_ret < 0:
                        wins += 1

                count = len(returns)
                win_rate = (wins / count) if count>0 else None
                avg_ret = float(np.mean(returns)) if count>0 else None
                med_ret = float(np.median(returns)) if count>0 else None
                results.append({'symbol':symbol,'interval':interval,'period_days':per,'threshold':thr,'signals':count,'win_rate':win_rate,'avg_ret':avg_ret,'med_ret':med_ret})
                print(f"{symbol} {interval} per={per} thr={thr} signals={count} win_rate={win_rate} avg_ret={avg_ret}")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', default='JP225')
    parser.add_argument('--days', type=int, default=90)
    args = parser.parse_args()
    mapping = {
        'JP225':'^N225',
        'DE40':'^GDAXI',
        'NASDAQ_MINI':'NQ=F',
        'GOLD_SPOT':'GC=F'
    }
    yf_symbol = mapping.get(args.symbol, args.symbol)
    print(f"Running grid for {args.symbol} ({yf_symbol}) days={args.days}")
    res = run_grid(args.symbol, yf_symbol, days=args.days)
    out = pd.DataFrame(res)
    out_path = f"logs/grid_search_{args.symbol}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    out.to_csv(out_path, index=False)
    print(f"Results saved to {out_path}")


if __name__ == '__main__':
    main()
