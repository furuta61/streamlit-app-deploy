#!/usr/bin/env python3
"""
market_data_fetch.py
YFinance を使って市況データ（日経225, NASDAQ, 金, USDJPY など）を取得。
events.csv などと統合して CFD3 システムに反映可能な形式で出力します。
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os

# === 設定 ===
# Allow overriding the NASDAQ ticker used for fetching (some brokers expose NAS100/US100 etc.)
# Default to NASDAQ mini symbol (NQ=F) per user request
NASDAQ_TICKER = os.environ.get('NASDAQ_TICKER', 'NQ=F')
# TOPIX はシステムで扱わない（ユーザー指定）。TOPIX 関連の取得は行いません。

# Map logical names to lists of candidate tickers (try in order until data found)
SYMBOL_CANDIDATES = {
    # Prioritize ETF tickers that are stable on yfinance for JP225
    'JP225': ['1321.T', '1330.T', '^N225', 'NI225'],
    'NASDAQ': [NASDAQ_TICKER, 'QTOP.EUR', '^IXIC', 'NDX'],
    'GOLD': ['GC=F', 'GOLD360', 'XAUUSD=X'],
    'SILVER': ['SI=F', 'XAGUSD=X'],
    'NATURAL_GAS': ['NG=F', 'NGAS'],
    'DE40': ['^GDAXI', 'DAX']
}

OUTPUT_PATH = os.path.expanduser("~/Desktop/CFD3_AutoSystem/market_data.csv")


def fetch_market_data(days=30, interval="1h", use_cache=True, cache_path: str = None, cache_ttl_minutes: int = 60):
    """YFinance からデータを取得

    Returns a DataFrame with a 'date' column and one column per symbol (named by SYMBOLS values).
    """
    end = datetime.now()
    start = end - timedelta(days=days)
    # caching: if a recent CSV exists, reuse it to avoid repeated network calls
    cache_path = cache_path or OUTPUT_PATH
    if use_cache and os.path.isfile(cache_path):
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_path))
        age_min = (datetime.now() - mtime).total_seconds() / 60.0
        if age_min <= cache_ttl_minutes:
            try:
                df = pd.read_csv(cache_path)
                df['date'] = pd.to_datetime(df['date'])
                print(f"📥 Using cached market data ({int(age_min)} minutes old): {cache_path}")
                return df
            except Exception:
                # fall through to re-download on read error
                pass

    print(f"📈 Fetching market data from {start.date()} to {end.date()}...")

    # We'll collect per-symbol frames and outer-join them on 'date'
    frames = []

    # NOTE: TOPIX は除外されました — TOPIX を取得/マップする処理は実行しません。

    # Fetch the rest of symbols using candidate lists
    for logical_name, candidates in SYMBOL_CANDIDATES.items():
        fetched = False
        for sym in candidates:
            try:
                per_sym_interval = "1d" if logical_name in ('JP225', 'TOPIX') else interval
                print(f"🔎 Trying {logical_name} candidate: {sym} (interval={per_sym_interval})")
                # Use Ticker.history which is often more reliable than yf.download for some tickers
                tk = yf.Ticker(sym)
                hist = tk.history(period=f"{days}d", interval=per_sym_interval)
                if hist is None or hist.empty:
                    # try a daily fallback if interval was intraday
                    if per_sym_interval != '1d':
                        hist = tk.history(period=f"{days}d", interval='1d')
                if hist is None or hist.empty:
                    print(f"⚠️ Candidate {sym} for {logical_name} returned no data")
                    continue
                # pick Close column or first numeric column
                series = None
                if 'Close' in hist.columns:
                    series = hist['Close']
                else:
                    for c in hist.columns:
                        try:
                            if pd.api.types.is_numeric_dtype(hist[c]):
                                series = hist[c]
                                break
                        except Exception:
                            continue
                if series is None or series.empty:
                    print(f"⚠️ Candidate {sym} for {logical_name} contained no usable numeric column")
                    continue
                tmp = pd.DataFrame({'date': series.index, logical_name: series.values})
                tmp['date'] = pd.to_datetime(tmp['date'])
                try:
                    tmp['date'] = tmp['date'].dt.tz_convert(None)
                except Exception:
                    try:
                        tmp['date'] = tmp['date'].dt.tz_localize(None)
                    except Exception:
                        pass
                frames.append(tmp[['date', logical_name]])
                print(f"✅ Fetched {logical_name} using {sym}")
                fetched = True
                break
            except Exception as e:
                print(f"⚠️ Candidate {sym} for {logical_name} failed: {e}")
                continue
        if not fetched:
            print(f"❌ All candidates failed for {logical_name}; appending empty frame")
            frames.append(pd.DataFrame(columns=['date', logical_name]))

    # Merge all symbol frames on 'date' using outer join, then sort by date
    # filter out any frames that don't have a 'date' column (safety)
    frames = [fr for fr in frames if isinstance(fr, pd.DataFrame) and 'date' in fr.columns]
    if not frames:
        df = pd.DataFrame()
    else:
        df = frames[0]
        for fr in frames[1:]:
            df = pd.merge(df, fr, on='date', how='outer')
        df = df.sort_values('date').reset_index(drop=True)

    # (TOPIX is intentionally not included in this pipeline)

    # Create pipeline aliases expected by weekly_events_update.py
    # GOLD -> GOLD_SPOT, NASDAQ -> NASDAQ_MINI
    try:
        if 'GOLD' in df.columns and 'GOLD_SPOT' not in df.columns:
            df['GOLD_SPOT'] = pd.to_numeric(df['GOLD'], errors='coerce')
            df['GOLD_SPOT_source'] = 'yf'
            df['GOLD_SPOT_interval'] = '1h'
        if 'NASDAQ' in df.columns and 'NASDAQ_MINI' not in df.columns:
            df['NASDAQ_MINI'] = pd.to_numeric(df['NASDAQ'], errors='coerce')
            df['NASDAQ_MINI_source'] = 'yf'
            df['NASDAQ_MINI_interval'] = '1h'
    except Exception:
        pass

    print(f"✅ Downloaded {len(df)} rows.")
    # save cache
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        df.to_csv(cache_path, index=False, encoding="utf-8-sig")
    except Exception:
        pass
    return df
    all_data = []
    for label, td_symbol in SYMBOLS.items():
        print(f"📈 取得中: {label} ({td_symbol})")

        # まず両方取得を試みる（比較のため）
        twelve_df = fetch_twelve_data(td_symbol, outputsize=days)
        yf_symbol = YF_MAP.get(label, label)
        yf_df = fetch_yfinance(yf_symbol, days=days)

        chosen_df = None
        meta: Dict[str, Optional[float]] = {"used": None, "mismatch_pct": None}

        # 最新値を取り出す補助
        def latest_price(df: Optional[pd.DataFrame]) -> Optional[float]:
            if df is None or df.empty:
                return None
            try:
                # assume date column exists
                df2 = df.copy()
                df2['date'] = pd.to_datetime(df2['date'])
                df2 = df2.sort_values('date')
                return float(df2['price'].dropna().iloc[-1])
            except Exception:
                return None

        t_latest = latest_price(twelve_df)
        y_latest = latest_price(yf_df)

        # Decide which source to use
        if t_latest is None and y_latest is None:
            print(f"❌ {label}: データ取得失敗（Twelve + yfinance両方）")
            continue
        elif t_latest is None:
            chosen_df = yf_df
            meta['used'] = 'yfinance'
            meta['mismatch_pct'] = None
            print(f"→ {label}: Twelve 欠落、yfinance({yf_symbol}) を使用")
        elif y_latest is None:
            chosen_df = twelve_df
            meta['used'] = 'twelve'
            meta['mismatch_pct'] = None
            print(f"→ {label}: yfinance 欠落、Twelve を使用（source={td_symbol}）")
        else:
            # both present -> compute mismatch
            try:
                mismatch = abs(t_latest - y_latest) / (y_latest if y_latest != 0 else float('nan'))
            except Exception:
                mismatch = float('nan')
            meta['mismatch_pct'] = float(mismatch) if not pd.isna(mismatch) else None
            if mismatch is None or pd.isna(mismatch):
                # fallback to yfinance conservatively
                chosen_df = yf_df
                meta['used'] = 'yfinance'
                print(f"→ {label}: mismatch 判定不能、保守的に yfinance を使用")
            elif mismatch > 0.05:
                chosen_df = yf_df
                meta['used'] = 'yfinance'
                print(f"⚠️ {label}: mismatch {mismatch:.3f} (>5%) - yfinance にフォールバック ({yf_symbol})")
            else:
                chosen_df = twelve_df
                meta['used'] = 'twelve'
                print(f"→ {label}: mismatch {mismatch:.3f} (<=5%) - Twelve を使用")

        # attach symbol and meta to chosen_df rows
        if chosen_df is not None and not chosen_df.empty:
            chosen_df = chosen_df.copy()
            chosen_df['symbol'] = label
            # store meta as JSON-like string per row (same for all rows of the symbol)
            try:
                import json as _json
                chosen_df['meta'] = _json.dumps(meta, ensure_ascii=False)
            except Exception:
                chosen_df['meta'] = str(meta)
            all_data.append(chosen_df)

    if not all_data:
        raise RuntimeError("❌ すべての銘柄でデータ取得に失敗しました。")

    result = pd.concat(all_data, ignore_index=True)
    result.sort_values(by=["symbol", "date"], inplace=True)
    # Save CSV with meta column
    result.to_csv(output_path, index=False)
    print(f"✅ マーケットデータ保存完了: {output_path}")
    return result


def save_market_data(df: pd.DataFrame, path: str = OUTPUT_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"💾 Saved to: {path}")


if __name__ == "__main__":
    df = fetch_market_data()
    save_market_data(df)
