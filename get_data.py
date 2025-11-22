#!/usr/bin/env python3
"""
get_data.py
- config.yaml の symbols を読み、yfinance で 30分足（interval=30m）と 4時間足（interval=4h）を取得して CSV に保存
- 保存先: ./data/<KEY>/exchange_symbol_31.csv (30分), exchange_symbol_241.csv (4時間)
- 実行ログは ./output/log.txt に追記
注意: TradingView のシンボル表記と yfinance のチケット名は異なる場合があります。
      ファイル内の `TV_TO_YF` マッピングを必要に応じて編集してください。
"""
import os
import sys
import yaml
import logging
from datetime import datetime
import pandas as pd

try:
    import yfinance as yf
except Exception as e:
    print("yfinance が import できません: pip install yfinance", file=sys.stderr)
    raise

ROOT = os.path.dirname(os.path.abspath(__file__))

LOG_PATH = os.path.join(ROOT, "output", "log.txt")

# TradingView の表記 -> yfinance のチケット名（必要に応じて編集）
TV_TO_YF = {
    "FOREXCOM:JP225": "^N225",   # 日経
    "FOREXCOM:NAS100": "^NDX",  # NASDAQ 100
    "TVC:GOLD": "GC=F",         # Gold futures
    # 旧: US30 は運用対象外に（残しておいても害はないが取得対象からは外れる）
    "FOREXCOM:US30": "YM=F",     # Dow futures (US30相当)
    # 新: GER40 は DAX 指数（Yahooは ^GDAXI）
    "FOREXCOM:GER40": "^GDAXI",
}


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def log(msg):
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{t} {msg}\n"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)
    print(line, end="")


def load_config():
    cfg_path = os.path.join(ROOT, "config.yaml")
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f"config.yaml not found at {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def tv_to_yf(tv_sym):
    if tv_sym in TV_TO_YF:
        return TV_TO_YF[tv_sym]
    # fallback: take portion after ':'
    if ":" in tv_sym:
        return tv_sym.split(":", 1)[1]
    return tv_sym


def fetch_and_save(yf_ticker, interval, period, out_csv):
    # yfinance uses e.g. interval='30m', '4h'
    try:
        df = yf.download(tickers=yf_ticker, period=period, interval=interval, progress=False)
    except Exception as e:
        log(f"ERROR fetching {yf_ticker} {interval}: {e}")
        return False
    if df is None or df.empty:
        log(f"WARN empty data for {yf_ticker} {interval}")
        return False
    # Flatten MultiIndex columns if present (yfinance sometimes returns multi-level cols per ticker)
    try:
        if hasattr(df.columns, "levels") and len(getattr(df.columns, "levels", [])) > 1:
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    except Exception:
        pass
    # ensure index name and column order
    df.index.name = 'datetime'
    # Keep a stable subset ordering; include Adj Close only if exists
    wanted = [c for c in ['Open','High','Low','Close','Adj Close','Volume'] if c in df.columns]
    if wanted:
        df = df[wanted]
    ensure_dir(os.path.dirname(out_csv))
    df.to_csv(out_csv)
    log(f"Saved {out_csv} rows={len(df)}")
    return True


def main():
    cfg = load_config()
    data_path = os.path.join(ROOT, cfg.get('data_path', './data/'))
    output_path = os.path.join(ROOT, cfg.get('output_path', './output/'))
    ensure_dir(output_path)
    ensure_dir(data_path)

    symbols = cfg.get('symbols', {})
    if not symbols:
        raise ValueError('no symbols in config.yaml')

    log('=== get_data.py start ===')
    for key, tv_sym in symbols.items():
        yf_ticker = tv_to_yf(tv_sym)
        subdir = os.path.join(data_path, key)
        ensure_dir(subdir)
        # filenames as requested
        exchange = tv_sym.split(":")[0] if ":" in tv_sym else "GEN"
        symbol = tv_sym.split(":")[-1]
        f30 = os.path.join(subdir, f"{exchange}_{symbol}_31.csv")
        f4h = os.path.join(subdir, f"{exchange}_{symbol}_241.csv")

        log(f"Fetching {key} TV:{tv_sym} -> yf:{yf_ticker}")
        # fetch 30m: period=7d (change if you want more history)
        ok30 = fetch_and_save(yf_ticker, '30m', '7d', f30)
        # fetch 4h: period=60d
        ok4h = fetch_and_save(yf_ticker, '4h', '60d', f4h)

        if not (ok30 or ok4h):
            log(f"ERROR: failed to fetch any data for {key} ({tv_sym})")
    log('=== get_data.py end ===')


if __name__ == '__main__':
    main()
