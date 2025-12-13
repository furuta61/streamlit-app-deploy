#!/usr/bin/env python3
"""
backtest_auto_tp.py
Simple backtest utility to evaluate how often the STRONG_GO auto-TP logic would have
been applied within a given horizon after entry dates found in an internal events CSV.

Behavior (lightweight):
 - Reads the latest internal CSV (or a provided one).
 - For each row with type == 'STRONG_GO', fetches market history and re-evaluates the
   auto-TP trigger condition on each subsequent day up to horizon_days.
 - Records whether the auto-TP trigger would have fired and on which date.
 - Outputs a CSV summary and prints aggregate stats.

This is intentionally lightweight (fast to run) and focuses on the auto-TP trigger rate.
"""

import argparse
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import timedelta
import logging
import sys
import os

# Ensure project root is on sys.path so we can import project modules when running from scripts/
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# import project's market data fetcher
from market_data_fetch import fetch_market_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('backtest_auto_tp')


def evaluate_trigger_for_entry(series, entry_index, signal, atr_period=14, sma_period=20, mom_window=5, rsi_buy=45.0, rsi_sell=55.0, relax_score_threshold=0.9, combined_score=0.0):
    """
    Given a pandas Series (datetime-indexed) of prices, and entry index (pd.Timestamp),
    evaluate day-by-day whether the STRONG_GO auto-TP trigger condition would fire.
    Returns (triggered: bool, trigger_date: Timestamp or None, reason: str)
    """
    # ensure series is sorted by date ascending
    s = series.sort_index()
    dates = s.index
    # find position of entry_index in dates
    try:
        start_pos = dates.get_loc(entry_index)
    except Exception:
        # if entry date not present exactly, find the first date after entry
        try:
            start_pos = dates.searchsorted(entry_index)
        except Exception:
            return (False, None, '')

    # iterate subsequent days
    for i in range(start_pos + 1, len(dates)):
        window = s.iloc[:i+1]
        if len(window) < max(20, sma_period):
            continue
        prices = window.tail(60)
        # ATR proxy
        try:
            atr = prices.pct_change().abs().rolling(atr_period).mean().iloc[-1] * prices.mean()
            if pd.isna(atr) or atr == 0:
                atr = 0.0
        except Exception:
            atr = 0.0
        # SMA
        try:
            sma = prices.rolling(sma_period).mean().iloc[-1]
        except Exception:
            sma = np.nan
        # RSI (14)
        try:
            delta = prices.diff().dropna()
            up = delta.clip(lower=0).rolling(14).mean()
            down = -delta.clip(upper=0).rolling(14).mean()
            rs = (up / down).replace([np.inf, -np.inf], np.nan)
            rsi = 100 - (100 / (1 + rs))
            rsi = float(rsi.iloc[-1]) if not rsi.empty else 50.0
        except Exception:
            rsi = 50.0
        # momentum
        try:
            momentum = prices.pct_change(periods=mom_window).iloc[-1]
            momentum = float(momentum)
        except Exception:
            momentum = 0.0
        momentum_thresh = -0.01
        if combined_score and float(combined_score) > relax_score_threshold:
            momentum_thresh = -0.003
        trigger = False
        last_price = float(prices.iloc[-1])
        if signal == 'BUY':
            if (momentum < momentum_thresh) or (not pd.isna(sma) and last_price < sma) or (rsi < rsi_buy):
                trigger = True
        else:
            if (momentum > abs(momentum_thresh)) or (not pd.isna(sma) and last_price > sma) or (rsi > rsi_sell):
                trigger = True
        if trigger:
            reason = f"atr={float(atr):.4f}, rsi={float(rsi):.2f}, mom={float(momentum):.4f}"
            return (True, dates[i], reason)
    return (False, None, '')


def simulate_trade(series, entry_index, entry_price, TP, SL, signal, lot_size, pv=1.0, horizon_days=60, slippage=0.0):
    """
    Simulate a single trade by walking forward through `series` (datetime-indexed closes).
    Returns dict with exit_date, exit_price, exit_reason (TP/SL/HORIZON/NO_DATA), profit_jpy.
    Assumptions:
      - series contains close prices at sufficient frequency (daily/hourly). We check close values only.
      - If both TP and SL are met on the same close, TP takes precedence (conservative for realized gains). Documented.
      - slippage is applied as absolute price adverse move (e.g., 0.01 means 0.01 price worse on exit).
    """
    res = {'exit_date': None, 'exit_price': None, 'exit_reason': 'NO_DATA', 'profit_jpy': 0.0}
    if series.empty:
        return res
    start_date = pd.to_datetime(entry_index)
    end_date = start_date + pd.Timedelta(days=horizon_days)
    window = series[(series.index >= start_date) & (series.index <= end_date)]
    if window.empty:
        # no data after entry
        res['exit_reason'] = 'NO_DATA'
        return res
    for ts, price in window.iteritems():
        p = float(price)
        # Check TP/SL depending on side
        if signal == 'BUY':
            tp_hit = (not pd.isna(TP)) and (p >= float(TP))
            sl_hit = (not pd.isna(SL)) and (p <= float(SL))
            if tp_hit and sl_hit:
                # both hit in same close: assume TP wins
                exit_price = float(TP) - slippage
                res['exit_date'] = ts
                res['exit_price'] = exit_price
                res['exit_reason'] = 'TP'
                break
            if tp_hit:
                exit_price = float(TP) - slippage
                res['exit_date'] = ts
                res['exit_price'] = exit_price
                res['exit_reason'] = 'TP'
                break
            if sl_hit:
                exit_price = float(SL) + slippage
                res['exit_date'] = ts
                res['exit_price'] = exit_price
                res['exit_reason'] = 'SL'
                break
        else:
            # SELL
            tp_hit = (not pd.isna(TP)) and (p <= float(TP))
            sl_hit = (not pd.isna(SL)) and (p >= float(SL))
            if tp_hit and sl_hit:
                exit_price = float(TP) + slippage
                res['exit_date'] = ts
                res['exit_price'] = exit_price
                res['exit_reason'] = 'TP'
                break
            if tp_hit:
                exit_price = float(TP) + slippage
                res['exit_date'] = ts
                res['exit_price'] = exit_price
                res['exit_reason'] = 'TP'
                break
            if sl_hit:
                exit_price = float(SL) - slippage
                res['exit_date'] = ts
                res['exit_price'] = exit_price
                res['exit_reason'] = 'SL'
                break
    # If neither hit within horizon, exit at last available price
    if res['exit_reason'] == 'NO_DATA':
        last_ts = window.index[-1]
        last_price = float(window.iloc[-1])
        res['exit_date'] = last_ts
        res['exit_price'] = last_price
        res['exit_reason'] = 'HORIZON'

    # compute profit
    if res['exit_price'] is not None and entry_price is not None and lot_size is not None:
        try:
            entry_f = float(entry_price)
            exit_f = float(res['exit_price'])
            qty = float(lot_size)
            if signal == 'BUY':
                profit = (exit_f - entry_f) * pv * qty
            else:
                profit = (entry_f - exit_f) * pv * qty
            res['profit_jpy'] = round(float(profit), 2)
        except Exception:
            res['profit_jpy'] = 0.0
    return res


def find_latest_internal_csv(logs_dir: Path) -> Path:
    # Prefer the most recent ifd_summary (final scored) CSV, fallback to events_scored_internal
    summary_files = sorted(logs_dir.glob('ifd_summary_*.csv'), key=lambda p: p.stat().st_mtime)
    if summary_files:
        return summary_files[-1]
    files = sorted(logs_dir.glob('events_scored_*_internal.csv'), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError('No internal or summary CSV files found in logs dir: %s' % logs_dir)
    return files[-1]


def main(internal_csv: str = None, horizon_days: int = 60, atr_period=14, sma_period=20, momentum_window=5, rsi_buy=45.0, rsi_sell=55.0, relax_score_threshold=0.9):
    logs_dir = Path.home() / 'Desktop' / 'CFD3_AutoSystem' / 'logs'
    if internal_csv is None:
        internal_path = find_latest_internal_csv(logs_dir)
    else:
        internal_path = Path(internal_csv)
        if not internal_path.exists():
            raise FileNotFoundError(f'Provided internal CSV not found: {internal_csv}')

    df = pd.read_csv(internal_path)
    # filter STRONG_GO rows
    if 'type' in df.columns:
        candidates = df[df['type'] == 'STRONG_GO'].copy()
    else:
        candidates = df.copy()
    results = []
    # fetch market data once for horizon + slack days
    market_days = horizon_days + 30
    logger.info('Fetching market data for last %d days (cache enabled)...', market_days)
    market_df = fetch_market_data(days=market_days, use_cache=True)
    # ensure date is datetime and indexable
    market_df['date'] = pd.to_datetime(market_df['date'])
    market_df = market_df.sort_values('date').reset_index(drop=True)

    for idx, row in candidates.iterrows():
        try:
            symbol = row.get('entry_source') or row.get('instrument') or ''
            if pd.isna(symbol) or symbol == '':
                continue
            entry_date = pd.to_datetime(row.get('date'))
            try:
                entry_price = float(row.get('entry'))
            except Exception:
                entry_price = None
            combined_score = row.get('combined_score', 0.0)
            # find market column
            market_col = None
            cand_names = [symbol, symbol.replace('_SPOT', ''), symbol.replace('_MINI', ''), 'GOLD_SPOT', 'GOLD']
            for c in cand_names:
                if c in market_df.columns:
                    market_col = c
                    break
            if market_col is None:
                # skip if no market column
                results.append({'index': idx, 'symbol': symbol, 'entry_date': entry_date, 'entry_price': entry_price, 'triggered': False, 'trigger_date': None, 'reason': 'no market column'})
                continue
            series = market_df[['date', market_col]].dropna()
            series = series.set_index('date')[market_col].astype(float)
            # restrict to window starting a few days before entry to include context
            window_start = entry_date - pd.Timedelta(days=10)
            series = series[series.index >= window_start]
            side = 'BUY' if float(row.get('combined_score', 0)) > 0 else 'SELL'
            TP = row.get('TP') if 'TP' in row.index else None
            SL = row.get('SL') if 'SL' in row.index else None
            lot_size = row.get('lot_size') if 'lot_size' in row.index else 1.0
            # point value map (JPY per point) - keep consistent with weekly_events_update
            point_value_map = {
                "JP225": 100,
                "NASDAQ_MINI": 20,
                "SP500": 50,
                "GOLD_SPOT": 100,
                "DE40": 100,
                "AAPL": 100,
                "MSFT": 100,
            }
            pv = point_value_map.get(symbol, 1.0)

            # Evaluate trigger info (whether auto-TP rule would have flagged)
            triggered, trig_date, reason = evaluate_trigger_for_entry(series, entry_date, side, atr_period=atr_period, sma_period=sma_period, mom_window=momentum_window, rsi_buy=rsi_buy, rsi_sell=rsi_sell, relax_score_threshold=relax_score_threshold, combined_score=combined_score)

            # Simulate realized P/L for requested horizons (default: use provided horizon_days)
            sim = simulate_trade(series, entry_date, entry_price, TP, SL, side, lot_size, pv=pv, horizon_days=horizon_days, slippage=0.0)

            results.append({
                'index': idx,
                'symbol': symbol,
                'entry_date': entry_date,
                'entry_price': entry_price,
                'triggered': bool(triggered),
                'trigger_date': str(trig_date) if trig_date is not None else None,
                'reason': reason,
                'exit_date': sim.get('exit_date'),
                'exit_price': sim.get('exit_price'),
                'exit_reason': sim.get('exit_reason'),
                'profit_jpy': sim.get('profit_jpy'),
                'lot_size': lot_size,
                'pv': pv,
            })
        except Exception as e:
            logger.exception('Error evaluating row %s: %s', idx, e)

    out_df = pd.DataFrame(results)
    out_path = logs_dir / f'backtest_auto_tp_{pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")}.csv'
    out_df.to_csv(out_path, index=False, encoding='utf-8-sig')
    total = len(out_df)
    trig = int(out_df['triggered'].sum()) if not out_df.empty else 0
    logger.info('Backtest complete: %d rows, %d triggered (%.2f%%)', total, trig, (trig/total*100.0) if total else 0.0)
    print(out_df.head(50).to_string(index=False))
    print('\nSaved results to:', out_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--internal-csv', help='internal CSV path (defaults to latest internal CSV in logs)')
    parser.add_argument('--horizon-days', type=int, default=60, help='How many days after entry to search for auto-TP trigger')
    parser.add_argument('--atr-period', type=int, default=14)
    parser.add_argument('--sma-period', type=int, default=20)
    parser.add_argument('--momentum-window', type=int, default=5)
    parser.add_argument('--rsi-buy', type=float, default=45.0)
    parser.add_argument('--rsi-sell', type=float, default=55.0)
    parser.add_argument('--relax-score-threshold', type=float, default=0.9)
    args = parser.parse_args()
    main(internal_csv=args.internal_csv, horizon_days=args.horizon_days, atr_period=args.atr_period, sma_period=args.sma_period, momentum_window=args.momentum_window, rsi_buy=args.rsi_buy, rsi_sell=args.rsi_sell, relax_score_threshold=args.relax_score_threshold)
