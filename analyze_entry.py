#!/usr/bin/env python3
"""
analyze_entry.py
- ./data/ に保存された CSV を読み、SMA, MACD, RSI, ATR, Bollinger を計算して簡易判定を行う
- 結果を ./output/entry_result.json と ./output/entry_result.md に出力
"""
import os
import sys
import yaml
import re
import json
from datetime import datetime
import traceback
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_config():
    cfg_path = os.path.join(ROOT, 'config.yaml')
    if not os.path.exists(cfg_path):
        raise FileNotFoundError('config.yaml not found')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def sma(series, n):
    return series.rolling(n).mean()


def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()


def macd(series, n_fast=12, n_slow=26, n_sig=9):
    fast = ema(series, n_fast)
    slow = ema(series, n_slow)
    macd_line = fast - slow
    signal = ema(macd_line, n_sig)
    hist = macd_line - signal
    return macd_line, signal, hist


def rsi(series, n=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=n-1, adjust=False).mean()
    ma_down = down.ewm(com=n-1, adjust=False).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))


def atr(df, n=14):
    high = df['High']
    low = df['Low']
    close = df['Close']
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def bollinger(series, n=20, k=2):
    ma = series.rolling(n).mean()
    sd = series.rolling(n).std()
    upper = ma + k * sd
    lower = ma - k * sd
    return upper, lower


def analyze_symbol(key, cfg):
    data_dir = os.path.join(ROOT, cfg.get('data_path', './data/'))
    symbol_dir = os.path.join(data_dir, key)
    if not os.path.exists(symbol_dir):
        print(f"no data dir for {key}: {symbol_dir}")
        return None
    # find files
    files = os.listdir(symbol_dir)
    f30 = None
    f4h = None
    for fn in files:
        if fn.endswith('_31.csv'):
            f30 = os.path.join(symbol_dir, fn)
        if fn.endswith('_241.csv'):
            f4h = os.path.join(symbol_dir, fn)
    if not f30 and not f4h:
        print(f"no CSV for {key}")
        return None

    results = { 'instrument': key }

    # prefer 30m for entry signals, but use 4h to confirm trend
    def safe_read_price_csv(path):
        """Read CSV that may contain extra header lines from yfinance output.
        Finds the first row that looks like a datetime and uses the previous row as header.
        Falls back to pd.read_csv(path, index_col=0, parse_dates=True) if detection fails.
        """
        with open(path, 'r', encoding='utf-8') as fh:
            lines = fh.readlines()
        data_row = None
        for i, line in enumerate(lines):
            first = line.split(',', 1)[0].strip()
            # match ISO date like 2025-10-20 or with timezone
            if re.match(r"^\d{4}-\d{2}-\d{2}", first):
                data_row = i
                break
        if data_row is not None and data_row > 0:
            # try to find a header row within a few lines above the data row
            known_cols = {'Close', 'Open', 'High', 'Low', 'Volume', 'Adj Close', 'Price'}
            header_row = None
            for h in range(data_row - 1, max(-1, data_row - 6), -1):
                tokens = [t.strip() for t in lines[h].split(',') if t.strip()]
                if any(tok in known_cols for tok in tokens):
                    header_row = h
                    break
            # fallback to one-line-above-data if nothing found
            if header_row is None:
                header_row = data_row - 1
            try:
                # skip any rows between header and first data row (these often contain 'Ticker' or 'datetime' markers)
                skip = None
                if data_row - header_row > 1:
                    skip = list(range(header_row + 1, data_row))
                df = pd.read_csv(path, header=header_row, index_col=0, parse_dates=True, skiprows=skip)
                return df
            except Exception:
                pass
        # fallback
        return pd.read_csv(path, index_col=0, parse_dates=True)

    if f30 and os.path.exists(f30):
        df30 = safe_read_price_csv(f30)
        close30 = df30['Close']
        results['close_30'] = float(close30.iloc[-1])
        results['sma25_30'] = float(sma(close30,25).iloc[-1])
        results['sma75_30'] = float(sma(close30,75).iloc[-1])
        macd_line, signal, hist = macd(close30)
        results['macd_30'] = float(macd_line.iloc[-1])
        results['macd_signal_30'] = float(signal.iloc[-1])
        results['rsi_30'] = float(rsi(close30).iloc[-1])
        ub, lb = bollinger(close30)
        results['bb_upper_30'] = float(ub.iloc[-1])
        results['bb_lower_30'] = float(lb.iloc[-1])
    else:
        df30 = None

    if f4h and os.path.exists(f4h):
        df4 = safe_read_price_csv(f4h)
        close4 = df4['Close']
        results['close_4h'] = float(close4.iloc[-1])
        results['sma25_4h'] = float(sma(close4,25).iloc[-1])
        results['sma75_4h'] = float(sma(close4,75).iloc[-1])
        macd_line4, signal4, hist4 = macd(close4)
        results['macd_4h'] = float(macd_line4.iloc[-1])
        results['macd_signal_4h'] = float(signal4.iloc[-1])
        results['atr_4h'] = float(atr(df4).iloc[-1])
    else:
        df4 = None

    # scoring (simple rules)
    tech_score = 0
    if 'sma25_30' in results and 'sma75_30' in results and results['sma25_30'] > results['sma75_30']:
        tech_score += 2
    if 'macd_30' in results and 'macd_signal_30' in results and results['macd_30'] > results['macd_signal_30']:
        tech_score += 2
    if 'rsi_30' in results and results['rsi_30'] > 60:
        tech_score += 1
    if 'atr_4h' in results:
        tech_score += 1

    # decision thresholds
    if tech_score >= 5:
        decision = 'STRONG_GO'
    elif tech_score >= 3:
        decision = 'GO'
    else:
        decision = 'WAIT'

    results['tech_score'] = tech_score
    results['decision'] = decision

    return results


def main():
    cfg = load_config()
    symbols = cfg.get('symbols', {})
    out = {
        'run_id': datetime.utcnow().strftime('%Y%m%dT%H%M%SZ'),
        'results': []
    }
    for key in symbols.keys():
        r = analyze_symbol(key, cfg)
        if r:
            out['results'].append(r)
    # write JSON
    out_path = os.path.join(ROOT, 'output', 'entry_result.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    # write simple markdown table
    md_path = os.path.join(ROOT, 'output', 'entry_result.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# Entry Results {datetime.utcnow().isoformat()}\n\n")
        f.write('|instrument|decision|tech_score|close_30|sma25_30|sma75_30|rsi_30|atr_4h|\n')
        f.write('|-|-|-|-|-|-|-|-|\n')
        for r in out['results']:
            f.write(f"|{r.get('instrument')},{r.get('decision')},{r.get('tech_score')},{r.get('close_30', '-')},{r.get('sma25_30','-')},{r.get('sma75_30','-')},{r.get('rsi_30','-')},{r.get('atr_4h','-')}|\n")

    print(f"Wrote: {out_path}, {md_path}")


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # log traceback to output/log.txt for easier debugging by user
        out_dir = os.path.join(ROOT, 'output')
        os.makedirs(out_dir, exist_ok=True)
        log_path = os.path.join(out_dir, 'log.txt')
        tb = traceback.format_exc()
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(datetime.utcnow().isoformat() + ' ERROR analyze_entry.py\n')
            f.write(tb + '\n')
        # also print to stderr so the user sees it in terminal
        print(tb, file=sys.stderr)
        raise
