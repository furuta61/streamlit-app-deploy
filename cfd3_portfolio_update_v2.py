# -*- coding: utf-8 -*-
"""
CFD3 Pro System 	6 v2 (JP225 / NAS100 / XAUUSD / US30 / COPPER)
- Entry Mode
- JSON  Markdown
改良点：
  * 動的ファイル探索（globで最新ファイルを自動選択）
  * 例外耐性（銘柄ごとにtry/except、空/破損CSVスキップ）
  * 判定と方向の不一致解消（方向=hold なら WAIT を強制）
  * 価格丸めの共通化（銘柄小数桁マップ）
  * ATRを本来のTR/EMA方式へ変更、NaN保護
  * 重複timestamp除去必須列検証
  * --only / --exclude オプション追加
"""

import argparse
import json
import os
import sys
import glob
from datetime import datetime

import pandas as pd
import numpy as np

# ===== 基本設定 =====
CAPITAL_JPY = 900_000
PER_LOT_ALLOCATION_JPY = 300_000
TRADE_MODE = "DAY6H"
INSTRUMENTS_BASE = ["JP225", "NAS100", "XAUUSD", "US30", "COPPER"]

NEWS_LOCK_POINTS = -2
LOTS_FOR = {"GO": 4, "STRONG_GO": 6}
# 銘柄ごとの丸め桁
DECIMALS = {
    "XAUUSD": 4,
    "COPPER": 4,    # XCUUSD/HG連動を想定
    "NAS100": 1,
    "US30": 1,
    "JP225": 1,
}

# 動的ファイル探索パターン（60/240）
GLOB_PATTERNS = {
    "JP225":  {"60": ["*JP225*60*.csv"],  "240": ["*JP225*240*.csv"]},
    "NAS100": {"60": ["*NAS100*60*.csv"], "240": ["*NAS100*240*.csv"]},
    "XAUUSD": {"60": ["*GOLD*60*.csv", "*XAUUSD*60*.csv"], "240": ["*GOLD*240*.csv", "*XAUUSD*240*.csv"]},
    "US30":   {"60": ["*US30*60*.csv"],   "240": ["*US30*240*.csv"]},
    "COPPER": {"60": ["*XCUUSD*60*.csv", "*COPPER*60*.csv", "*HG1!*60*.csv"],
               "240":["*XCUUSD*240*.csv","*COPPER*240*.csv","*HG1!*240*.csv"]},
}

# ===== 便利関数 =====
def latest_match(data_dir: str, patterns):
    """globで最も新しいファイルを返す。なければNone。"""
    if not patterns:
        return None
    candidates = []
    for p in patterns:
        candidates.extend(glob.glob(os.path.join(data_dir, p)))
    if not candidates:
        return None
    # 変更時刻が新しいもの
    candidates.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return candidates[0]

def require_columns(df: pd.DataFrame, needed=("time","open","high","low","close")):
    cols = [c.lower().strip() for c in df.columns]
    df.columns = cols
    missing = [c for c in needed if c not in cols]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    return df

def normalize(df: pd.DataFrame) -> pd.DataFrame:
    # 列名整形 & 日付列確定
    df.columns = [c.lower().strip() for c in df.columns]
    # 時刻列は数値（unix秒/ms）や文字列の可能性があるため、賢くパースする
    def _parse_time(col):
        s = df[col]
        # 数値型の場合は最大値を見て秒かミリ秒か推定
        if pd.api.types.is_integer_dtype(s) or pd.api.types.is_float_dtype(s):
            mx = pd.to_numeric(s, errors="coerce").abs().dropna()
            if not mx.empty:
                mval = mx.max()
                if mval > 1e12:
                    return pd.to_datetime(s, unit='ms', errors='coerce')
                if mval > 1e9:
                    return pd.to_datetime(s, unit='s', errors='coerce')
        # 文字列型で数字のみなら数値化して上と同様に判断
        if s.dtype == object:
            # 簡易チェック：値が数字のみで構成されているか
            try:
                sample = s.dropna().astype(str).iloc[0]
            except Exception:
                sample = ''
            if sample.isdigit():
                si = pd.to_numeric(s, errors='coerce')
                if not si.dropna().empty:
                    mval = si.abs().max()
                    if mval > 1e12:
                        return pd.to_datetime(si, unit='ms', errors='coerce')
                    if mval > 1e9:
                        return pd.to_datetime(si, unit='s', errors='coerce')
        # フォールバック：pandas に任せる
        return pd.to_datetime(s, errors='coerce')

    if "time" in df.columns:
        df["time"] = _parse_time("time")
    elif "datetime" in df.columns:
        df["time"] = _parse_time("datetime")
    elif "date" in df.columns:
        df["time"] = _parse_time("date")
    else:
        raise ValueError("No time/datetime/date column")
    # 必須列
    df = require_columns(df, ("time","open","high","low","close"))
    # 時系列整備
    df = df.dropna(subset=["time"]).sort_values("time")
    # 重複timestampは最後を採用
    df = df[~df["time"].duplicated(keep="last")].reset_index(drop=True)
    # 数値列をfloat化
    for c in ["open","high","low","close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open","high","low","close"])
    return df

def true_range(df):
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr

def ema(series: pd.Series, span: int):
    return series.ewm(span=span, adjust=False).mean()

def indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    df["sma25"] = c.rolling(25, min_periods=25).mean()
    df["sma75"] = c.rolling(75, min_periods=75).mean()
    ema12 = ema(c, 12)
    ema26 = ema(c, 26)
    df["macd"] = ema12 - ema26
    df["signal"] = ema(df["macd"], 9)
    # RSI（Wilder）
    delta = c.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    roll_up = gain.ewm(alpha=1/14, adjust=False).mean()
    roll_dn = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = roll_up / (roll_dn + 1e-12)
    df["rsi"] = 100 - (100 / (1 + rs))
    # ATR（真のレンジのEMA）
    tr = true_range(df)
    df["atr"] = ema(tr, 14)
    # BB
    df["bb_basis"] = c.rolling(20, min_periods=20).mean()
    df["bb_upper"] = df["bb_basis"] + 2 * c.rolling(20, min_periods=20).std(ddof=0)
    df["bb_lower"] = df["bb_basis"] - 2 * c.rolling(20, min_periods=20).std(ddof=0)
    return df

def round_price(symbol: str, price: float) -> float:
    decimals = DECIMALS.get(symbol, 2)
    return round(float(price), decimals)

def score_entry(row4h, symbol: str, news_lock: bool=False) -> int:
    s = 0
    # トレンド
    if row4h["sma25"] > row4h["sma75"]:
        s += 2
    if row4h["macd"] > row4h["signal"]:
        s += 2
    # モメンタム
    if row4h["rsi"] > 52:
        s += 1
    if row4h["close"] > row4h["bb_basis"]:
        s += 1
    # 安定度（ATR>0で+1）
    if not np.isnan(row4h["atr"]) and row4h["atr"] > 0:
        s += 1
    # 代替/景気系を僅かに優遇
    if symbol in ("US30","COPPER"):
        s += 1
    if news_lock:
        s += NEWS_LOCK_POINTS
    return max(0, int(s))

def decide_from_score(s: int) -> str:
    if s >= 6: return "STRONG_GO"
    if s >= 4: return "GO"
    return "WAIT"

def entry_direction(row4h) -> str:
    if row4h["sma25"] > row4h["sma75"] and row4h["macd"] > row4h["signal"]:
        return "buy"
    if row4h["sma25"] < row4h["sma75"] and row4h["macd"] < row4h["signal"]:
        return "sell"
    return "hold"

def build_order(symbol: str, row4h, decision: str, direction: str, price_override=None):
    # price_override を優先して使う（テストや外部ソースから供給される価格）
    if price_override is not None:
        price = float(price_override)
    else:
        price = float(row4h["close"])
    atr = float(row4h["atr"]) if not np.isnan(row4h.get("atr", np.nan)) else 0.0

    # WAITまたは方向不明ならIFDは空
    if decision == "WAIT" or direction == "hold":
        return {
            "instrument": symbol,
            "direction": direction,
            "signal_rating": 2 if decision=="WAIT" else 0,
            "decision": "WAIT",
            "lots": 0,
            "entry_order": {"type": "-", "price": round_price(symbol, price)},
            "order_type": "-",
            "ifd_legs": [],
            "cut_condition": {"sma": "SMA25<SMA75", "macd": "MACD<Signal"}
        }

    # ATR連動
    tp1 = price + (atr * 1.2 if direction == "buy" else -atr * 1.2)
    tp2 = price + (atr * 1.8 if direction == "buy" else -atr * 1.8)
    sl  = price - (atr * 2.5 if direction == "buy" else -atr * 2.5)

    lots = LOTS_FOR.get(decision, 0)
    return {
        "instrument": symbol,
        "direction": direction,
        "signal_rating": 6 if decision=="STRONG_GO" else 4 if decision=="GO" else 2,
        "decision": decision,
        "lots": lots,
        "entry_order": {"type": "limit", "price": round_price(symbol, price)},
        "order_type": "指値",
        "ifd_legs": [
            {"name": "IFD-1",
             "oco": {"take_profit": {"price": round_price(symbol, tp1)},
                     "stop_loss":   {"price": round_price(symbol, sl)}}},
            {"name": "IFD-2",
             "oco": {"take_profit": {"price": round_price(symbol, tp2)},
                     "stop_loss":   {"price": round_price(symbol, sl)},
                     "trailing_stop": {
                         "activate_after": round_price(symbol, tp2),
                         "distance": round_price(symbol, atr * 1.0)
                     }}}
        ],
        "cut_condition": {"sma": "SMA25<SMA75", "macd": "MACD<Signal"}
    }

def hold_decision(row4h) -> str:
    if (row4h["sma25"] < row4h["sma75"]) or (row4h["macd"] < row4h["signal"]):
        return "CUT"
    return "HOLD"

def print_json_and_table(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    rows = []
    for od in payload["orders"]:
        if od["decision"] == "WAIT" or not od["ifd_legs"]:
            tp1 = tp2 = sl = "-"
            entry_price = od["entry_order"]["price"]
        else:
            tp1 = od["ifd_legs"][0]["oco"]["take_profit"]["price"]
            tp2 = od["ifd_legs"][1]["oco"]["take_profit"]["price"]
            sl  = od["ifd_legs"][0]["oco"]["stop_loss"]["price"]
            entry_price = od["entry_order"]["price"]
        rows.append([
            payload["trade_mode"], od["instrument"], od["direction"],
            entry_price, sl, tp1, tp2, od["order_type"],
            od["decision"], str(payload.get("news_lock", False)).lower(),
            "★★★★★" if od["decision"]=="STRONG_GO" else "★★★★☆" if od["decision"]=="GO" else "★★☆☆☆",
            od["lots"], "SMA25<SMA75 or MACD<Signal"
        ])
    headers = ["trade_mode","銘柄","方向","entry_price","SL","TP1","TP2","order_type","判定","ニュースロック","推奨度","ロット","CUT条件"]
    sys.stdout.write("\n")
    sys.stdout.write("| " + " | ".join(headers) + " |\n")
    sys.stdout.write("|" + "|".join(["---"]*len(headers)) + "|\n")
    for r in rows:
        sys.stdout.write("| " + " | ".join(map(str, r)) + " |\n")

# ===== メイン =====
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="./data", help="CSVディレクトリ")
    ap.add_argument("--hold", action="store_true", help="Hold Mode（HOLD/CUT）")
    ap.add_argument("--newslock", action="store_true", help="ニュースロック(-2点)")
    ap.add_argument("--only", default="", help="対象銘柄をカンマ区切りで指定（例: XAUUSD,US30）")
    ap.add_argument("--exclude", default="", help="除外銘柄をカンマ区切りで指定")
    args = ap.parse_args()

    only = [s.strip().upper() for s in args.only.split(",") if s.strip()] if args.only else []
    exclude = [s.strip().upper() for s in args.exclude.split(",") if s.strip()] if args.exclude else []

    instruments = INSTRUMENTS_BASE[:]
    if only:
        instruments = [s for s in instruments if s in only]
    if exclude:
        instruments = [s for s in instruments if s not in exclude]

    run_id = datetime.now().strftime("%Y-%m-%d-%H%M")
    orders = []

    # Load recent TradingView webhook prices (if available) to prefer for certain symbols
    def load_tradingview_prices(path="output/tradingview.jsonl"):
        prices = {}
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    for ln in fh:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            obj = json.loads(ln)
                            data = obj.get("data") or obj
                            sym = data.get("symbol")
                            price = data.get("price")
                            if sym and price is not None:
                                prices[sym.upper()] = float(price)
                        except Exception:
                            continue
        except Exception:
            pass
        return prices

    tv_prices = load_tradingview_prices()

    for sym in instruments:
        try:
            # 最新の4h CSVを探索
            fp = latest_match(args.data, GLOB_PATTERNS.get(sym, {}).get("240", []))
            if not fp:
                print(f"[WARN] No 4h CSV for {sym}", file=sys.stderr)
                continue
            df = pd.read_csv(fp)
            if df.empty:
                print(f"[WARN] Empty CSV for {sym}: {fp}", file=sys.stderr)
                continue

            df = normalize(df)
            if len(df) < 80:  # 指標計算の最低本数（SMA75等）
                print(f"[WARN] Not enough bars for {sym}: {len(df)}", file=sys.stderr)
                continue

            df = indicators(df)
            row4h = df.iloc[-1]

            # For XAUUSD decide price_to_use without modifying row4h (avoid SettingWithCopyWarning)
            price_to_use = None
            if sym == "XAUUSD":
                # Accept a few possible tradingview keys (some webhooks use different casings/aliases)
                tvp = tv_prices.get("XAUUSD") or tv_prices.get("XAU") or tv_prices.get("GOLD")
                try:
                    csv_price = float(row4h["close"])
                except Exception:
                    csv_price = None
                used_source = "csv"
                # If CSV price is missing or outside reasonable gold-spot bounds, prefer TradingView
                # Reasonable bounds: gold in USD per troy oz typically between 300 and 5000.
                if csv_price is None or csv_price < 300 or csv_price > 5000:
                    if tvp is not None:
                        price_to_use = tvp
                        used_source = "tradingview"
                else:
                    # Fallback: if CSV and TV differ by large percent (>20%), prefer TV
                    if tvp is not None:
                        try:
                            if abs(csv_price - tvp) / max(tvp, 1e-9) > 0.20:
                                price_to_use = tvp
                                used_source = "tradingview"
                        except Exception:
                            pass
                if price_to_use is None:
                    price_to_use = csv_price
                # emit a short diagnostic so it's easier to trace in logs
                print(f"[INFO] XAUUSD price selection: csv={csv_price} tv={tvp} -> used={used_source}", file=sys.stderr)

            if args.hold:
                decision = hold_decision(row4h)
                od = {
                    "instrument": sym,
                    "direction": "-",
                    "signal_rating": None,
                    "decision": decision,
                    "lots": 0,
                    "entry_order": {"type": "-", "price": round_price(sym, row4h["close"])},
                    "order_type": "-",
                    "ifd_legs": [],
                    "cut_condition": {"sma": "SMA25<SMA75", "macd": "MACD<Signal"}
                }
                orders.append(od)
            else:
                s = score_entry(row4h, sym, news_lock=args.newslock)
                decision = decide_from_score(s)
                direction = entry_direction(row4h)

                # 方向が不明ならGO/STRONGを出さない（WAITへ強制）
                if direction == "hold" and decision != "WAIT":
                    decision = "WAIT"

                od = build_order(sym, row4h, decision, direction, price_override=price_to_use)
                orders.append(od)

        except Exception as e:
            print(f"[ERROR] {sym}: {e}", file=sys.stderr)
            continue

    payload = {
        "run_id": run_id,
        "capital_jpy": CAPITAL_JPY,
        "per_lot_allocation_jpy": PER_LOT_ALLOCATION_JPY,
        "trade_mode": TRADE_MODE,
        "news_lock": bool(args.newslock),
        "orders": orders
    }
    # Persist output JSON and append a short CSV summary for auditing
    try:
        os.makedirs("output", exist_ok=True)
        out_fp = os.path.join("output", f"ifd_{run_id}.json")
        with open(out_fp, "w", encoding="utf-8") as ofh:
            json.dump(payload, ofh, ensure_ascii=False, indent=2)
        # Append summary CSV to logs
        os.makedirs("logs", exist_ok=True)
        summary_fn = os.path.join("logs", f"ifd_summary_{datetime.now().strftime('%Y%m%d')}.csv")
        # If file not exists, write header
        write_header = not os.path.exists(summary_fn)
        with open(summary_fn, "a", encoding="utf-8") as sfh:
            if write_header:
                sfh.write("timestamp,run_id,instrument,decision,entry_price,lots\n")
            ts = datetime.now().isoformat()
            for od in orders:
                if od.get("entry_order") and isinstance(od["entry_order"], dict):
                    entry_price = od["entry_order"].get("price")
                else:
                    entry_price = ""
                sfh.write(f"{ts},{run_id},{od.get('instrument')},{od.get('decision')},{entry_price},{od.get('lots')}\n")
        print(f"[INFO] Saved IFD JSON to {out_fp}", file=sys.stderr)
        print(f"[INFO] Appended summary to {summary_fn}", file=sys.stderr)
    except Exception as e:
        print(f"[WARN] Failed to persist IFD output: {e}", file=sys.stderr)

    print_json_and_table(payload)

if __name__ == "__main__":
    main()
