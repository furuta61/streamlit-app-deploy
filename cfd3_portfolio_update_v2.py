# -*- coding: utf-8 -*-
"""
CFD3 Pro System 	6 v2 (JP225 / NAS100 / XAUUSD / GER40 / COPPER)
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
INSTRUMENTS_BASE = ["JP225", "NAS100", "XAUUSD", "GER40", "COPPER"]

NEWS_LOCK_POINTS = -2
LOTS_FOR = {"GO": 4, "STRONG_GO": 6}
# 銘柄別の閾値上書き（軽いチューニング）
# 既定: STRONG_GO >=6, GO >=4。GER40 はそれぞれ -1 して出やすくする。
THRESHOLD_OVERRIDES = {
    "GER40": {"STRONG_GO": 5, "GO": 3}
}
# 銘柄ごとの丸め桁
DECIMALS = {
    "XAUUSD": 4,
    "COPPER": 4,    # XCUUSD/HG連動を想定
    "NAS100": 1,
    "JP225": 1,
    "GER40": 1,
}

# 表示専用スケール（GMO表示向け）。内部計算は実価格のまま。
DISPLAY_SCALE = {
    # XAUUSD は GMO 画面の見た目に合わせて x100 を既定とする（必要なら環境変数で上書き）
    "XAUUSD": float(os.getenv("GMO_XAUUSD_DISPLAY_SCALE", "100")),
}
# 表示時の小数桁（指定がなければ DECIMALS を使用）
DISPLAY_DECIMALS = {
    # 例: GMOでは小数1桁などにしたい場合
    "XAUUSD": int(os.getenv("GMO_XAUUSD_DISPLAY_DECIMALS", "1")),
}

# 動的ファイル探索パターン（60/240）
GLOB_PATTERNS = {
    # 4Hは "240" と "241" の両方にマッチ（ツールによって表記が異なる）。60m系は "60" と "31" を許容。
    "JP225":  {
        "60":  ["*JP225*60*.csv", "**/*JP225*60*.csv", "*JP225*31*.csv", "**/*JP225*31*.csv"],
        "240": ["*JP225*240*.csv", "**/*JP225*240*.csv", "*JP225*241*.csv", "**/*JP225*241*.csv"],
    },
    "NAS100": {
        "60":  ["*NAS100*60*.csv", "**/*NAS100*60*.csv", "*NAS100*31*.csv", "**/*NAS100*31*.csv"],
        "240": ["*NAS100*240*.csv", "**/*NAS100*240*.csv", "*NAS100*241*.csv", "**/*NAS100*241*.csv"],
    },
    "XAUUSD": {
        "60":  ["*GOLD*60*.csv", "*XAUUSD*60*.csv", "**/*GOLD*60*.csv", "**/*XAUUSD*60*.csv", "*GOLD*31*.csv", "**/*GOLD*31*.csv", "*XAUUSD*31*.csv", "**/*XAUUSD*31*.csv"],
        "240": ["*GOLD*240*.csv", "*XAUUSD*240*.csv", "**/*GOLD*240*.csv", "**/*XAUUSD*240*.csv", "*GOLD*241*.csv", "**/*GOLD*241*.csv", "*XAUUSD*241*.csv", "**/*XAUUSD*241*.csv"],
    },
    "GER40":  {
        "60":  ["*GER40*60*.csv", "**/*GER40*60*.csv", "*GER40*31*.csv", "**/*GER40*31*.csv"],
        "240": ["*GER40*240*.csv", "**/*GER40*240*.csv", "*GER40*241*.csv", "**/*GER40*241*.csv"],
    },
    "COPPER": {
        "60":  ["*XCUUSD*60*.csv", "*COPPER*60*.csv", "*HG1!*60*.csv", "**/*XCUUSD*60*.csv", "**/*COPPER*60*.csv", "**/*HG1!*60*.csv", "*XCUUSD*31*.csv", "**/*XCUUSD*31*.csv", "*COPPER*31*.csv", "**/*COPPER*31*.csv"],
        "240": ["*XCUUSD*240*.csv","*COPPER*240*.csv","*HG1!*240*.csv", "**/*XCUUSD*240*.csv","**/*COPPER*240*.csv","**/*HG1!*240*.csv", "*XCUUSD*241*.csv","**/*XCUUSD*241*.csv","*COPPER*241*.csv","**/*COPPER*241*.csv"],
    },
}

# ===== 便利関数 =====
def latest_match(data_dir: str, patterns):
    """globで最も新しいファイルを返す。なければNone。"""
    if not patterns:
        return None
    candidates = []
    for p in patterns:
        candidates.extend(glob.glob(os.path.join(data_dir, p), recursive=True))
    if not candidates:
        return None
    # 変更時刻が新しいもの
    candidates.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return candidates[0]

def latest_match_for_tf(data_dir: str, sym: str, tf: str):
    """時間足別に優先パターンを切り替えて最新CSVを選ぶ。

    tf: '240' (4H) | '60' (1H) | '30' (30m)
    - 240: GLOB_PATTERNS[sym]['240'] を使用
    - 60 : '*60*' を優先し、無ければ '60' 定義全体から選択
    - 30 : '*31*' を優先し、無ければ '60' 定義全体から選択（ツール差異へのフォールバック）
    """
    tf = str(tf).lower()
    pats = GLOB_PATTERNS.get(sym, {})
    if tf in ("240", "4h"):
        return latest_match(data_dir, pats.get("240", []))
    if tf in ("60", "1h"):
        base = pats.get("60", [])
        # '*60*' を優先
        p60 = [p for p in base if "60" in p]
        fp = latest_match(data_dir, p60)
        return fp or latest_match(data_dir, base)
    if tf in ("30", "30m"):
        base = pats.get("60", [])
        # '*31*' を優先（30分ファイル）
        p30 = [p for p in base if "31" in p]
        fp = latest_match(data_dir, p30)
        return fp or latest_match(data_dir, base)
    # 未知 -> 240
    return latest_match(data_dir, pats.get("240", []))

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

def resample_to_4h(df: pd.DataFrame) -> pd.DataFrame:
    """60分足などから4時間足にOHLC再サンプリングする簡易関数。

    - 前提: df には time, open, high, low, close が存在し時系列整備済み
    - 出力: 4HにまとめたOHLC（欠損は除外）
    """
    try:
        d = df.copy()
        d["time"] = pd.to_datetime(d["time"], errors="coerce")
        d = d.dropna(subset=["time"]).sort_values("time")
        d = d.set_index("time")
        o = d["open"].resample("4H").first()
        h = d["high"].resample("4H").max()
        l = d["low"].resample("4H").min()
        c = d["close"].resample("4H").last()
        out = pd.concat([o, h, l, c], axis=1)
        out.columns = ["open","high","low","close"]
        out = out.dropna().reset_index().rename(columns={"time":"time"})
        return out
    except Exception:
        return pd.DataFrame(columns=["time","open","high","low","close"])  # empty

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

def display_price(symbol: str, price: float) -> float:
    """GMO向けの表示価格に変換（倍率と丸めを適用）。"""
    try:
        base = float(price)
    except Exception:
        return price
    scale = DISPLAY_SCALE.get(symbol, 1.0)
    dec = DISPLAY_DECIMALS.get(symbol, DECIMALS.get(symbol, 2))
    return round(base * scale, dec)

def score_entry(row4h, symbol: str, news_lock: bool=False) -> int:
    """方向に対して対称にスコアリング。

    - buy のとき: SMA25>SMA75, MACD>Signal, RSI>52, Close>BB基準 を評価
    - sellのとき: SMA25<SMA75, MACD<Signal, RSI<48, Close<BB基準 を評価
    - holdのとき: 最低限の安定度のみ（後段でWAITに強制されるため）
    """
    s = 0
    # まず方向を同一ロジックで決定
    dirn = entry_direction(row4h)

    sma_gt = bool(row4h["sma25"] > row4h["sma75"])
    sma_lt = bool(row4h["sma25"] < row4h["sma75"])
    macd_gt = bool(row4h["macd"] > row4h["signal"])
    macd_lt = bool(row4h["macd"] < row4h["signal"])
    rsi = float(row4h.get("rsi", np.nan)) if not pd.isna(row4h.get("rsi", np.nan)) else np.nan
    close = float(row4h.get("close", np.nan)) if not pd.isna(row4h.get("close", np.nan)) else np.nan
    bb_basis = float(row4h.get("bb_basis", np.nan)) if not pd.isna(row4h.get("bb_basis", np.nan)) else np.nan

    if dirn == "buy":
        if sma_gt:
            s += 2
        if macd_gt:
            s += 2
        if not np.isnan(rsi) and rsi > 52:
            s += 1
        if not np.isnan(close) and not np.isnan(bb_basis) and close > bb_basis:
            s += 1
    elif dirn == "sell":
        if sma_lt:
            s += 2
        if macd_lt:
            s += 2
        if not np.isnan(rsi) and rsi < 48:
            s += 1
        if not np.isnan(close) and not np.isnan(bb_basis) and close < bb_basis:
            s += 1
    else:
        # hold の場合は方向性スコアは乗せない（後でWAITに強制）
        pass

    # 安定度（ATR>0で+1）
    if not np.isnan(row4h["atr"]) and row4h["atr"] > 0:
        s += 1

    # 軽微な銘柄バイアス
    if symbol in ("COPPER",):
        s += 1
    # GER40 は方向に応じて 50ラインからの乖離に +1（軽い押し上げ）
    try:
        if symbol == "GER40" and not np.isnan(rsi):
            if (dirn == "buy" and rsi > 50) or (dirn == "sell" and rsi < 50):
                s += 1
    except Exception:
        pass

    if news_lock:
        s += NEWS_LOCK_POINTS
    return max(0, int(s))

def decide_from_score(s: int, symbol: str) -> str:
    # 既定値
    strong_go_th = 6
    go_th = 4
    # 銘柄別上書き
    ov = THRESHOLD_OVERRIDES.get((symbol or '').upper())
    if isinstance(ov, dict):
        strong_go_th = int(ov.get("STRONG_GO", strong_go_th))
        go_th = int(ov.get("GO", go_th))
    if s >= strong_go_th:
        return "STRONG_GO"
    if s >= go_th:
        return "GO"
    return "WAIT"

def entry_direction(row4h) -> str:
    if row4h["sma25"] > row4h["sma75"] and row4h["macd"] > row4h["signal"]:
        return "buy"
    if row4h["sma25"] < row4h["sma75"] and row4h["macd"] < row4h["signal"]:
        return "sell"
    return "hold"

def build_order(symbol: str, row4h, decision: str, direction: str, price_override=None,
                per_lot_overrides: dict | None = None, lots_for_map: dict | None = None,
                entry_type: str = "成行"):
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

    # 新: ユーザー目標のJPY/口固定方式（浅めのコツコツ運用）
    # STRONG_GO -> per_lot_jpy (試験値 2000)、GO -> 800
    # 1) 目標利確（JPY/口）: 引数の上書きを優先
    per_lot_jpy = None
    if per_lot_overrides and isinstance(per_lot_overrides, dict):
        try:
            per_lot_jpy = float(per_lot_overrides.get(decision)) if per_lot_overrides.get(decision) is not None else None
        except Exception:
            per_lot_jpy = None
    if per_lot_jpy is None:
        if decision == 'STRONG_GO':
            per_lot_jpy = 2000.0
        elif decision == 'GO':
            per_lot_jpy = 800.0

    # 各銘柄の1ポイントあたりのJPY換算値（運用時に検証が必要）
    point_value_map = {
        "JP225": 100.0,
        "NAS100": 20.0,
        # GER40（DAX CFD）: 仮のJPY換算（要ブローカー仕様に合わせ調整）
        # 30→80 に見直し（TP/SLをややタイトに）
        "GER40": 80.0,
        # 以下は概算／要確認: XAUUSD は USD 変動を JPY に換算する必要あり
        "XAUUSD": 150.0,
        # COPPER はブローカー依存。ここでは仮値（要 dry-run）
        "COPPER": 1000.0,
    }

    pv = float(point_value_map.get(symbol, 1.0))

    if per_lot_jpy is not None:
        # TP/SL を per_lot_jpy に合わせて計算
        try:
            tp_distance = float(per_lot_jpy) / pv
        except Exception:
            tp_distance = float(per_lot_jpy)
        sl_distance = tp_distance / 3.0
        if direction == "buy":
            tp1 = price + tp_distance
            tp2 = price + (tp_distance * 1.5)
            sl = price - sl_distance
        else:
            tp1 = price - tp_distance
            tp2 = price - (tp_distance * 1.5)
            sl = price + sl_distance
    else:
        # Fallback: ATRベース（既存ロジック）
        tp1 = price + (atr * 1.2 if direction == "buy" else -atr * 1.2)
        tp2 = price + (atr * 1.8 if direction == "buy" else -atr * 1.8)
        sl  = price - (atr * 2.5 if direction == "buy" else -atr * 2.5)

    # 2) ロット数: 引数の上書きを優先
    if lots_for_map and isinstance(lots_for_map, dict):
        lots = int(lots_for_map.get(decision, LOTS_FOR.get(decision, 0)))
    else:
        lots = LOTS_FOR.get(decision, 0)
    # エントリー種別
    entry_type = entry_type or "成行"
    entry_order_type = "market" if entry_type == "成行" else "limit"

    return {
        "instrument": symbol,
        "direction": direction,
        "signal_rating": 6 if decision=="STRONG_GO" else 4 if decision=="GO" else 2,
        "decision": decision,
        "lots": lots,
        # エントリー
        "entry_order": {"type": entry_order_type, "price": round_price(symbol, price)},
        "order_type": entry_type,
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
        # 表示用スケール（GMO向け）を適用
        sym = od.get("instrument")
        entry_disp = display_price(sym, entry_price) if isinstance(entry_price, (int, float)) else entry_price
        tp1_disp = display_price(sym, tp1) if isinstance(tp1, (int, float)) else tp1
        tp2_disp = display_price(sym, tp2) if isinstance(tp2, (int, float)) else tp2
        sl_disp  = display_price(sym, sl)  if isinstance(sl,  (int, float)) else sl
        rows.append([
            payload["trade_mode"], od["instrument"], od["direction"],
            entry_disp, sl_disp, tp1_disp, tp2_disp, od["order_type"],
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
    # 単方向（GMOスタイル）: GO/STRONG_GO の片側のみを出力（WAITや方向holdは除外）
    ap.add_argument("--single", action="store_true", help="単方向IFDのみ出力 (GO/STRONG_GO かつ buy/sell)")
    # 有効期限（失効タイムスタンプをpayloadに付与）
    ap.add_argument("--expiry-hours", type=int, default=0, help="何時間後に失効するか。0なら付与しない")
    # 4時間モードなど trade_mode を外部から指定可能に（既存定数を上書き）
    ap.add_argument("--trade-mode", default="", help="出力JSONのtrade_modeを上書き (例: DAY4H)")
    # 解析時間足: 4h/1h/30m を指定（既定:4h）
    # 複合指定（例: "4h+30m"）にも対応。先頭が上位足、後段がエントリー足として扱う。
    ap.add_argument("--tf", default="4h", help="解析時間足 (4h/1h/30m または 240/60/30)。複合は 4h+30m の形式で指定可能")
    # 手動でエントリー価格を上書き (カンマ区切り: 例 GER40=23762,JP225=38000)
    ap.add_argument("--entry-override", default="", help="銘柄=価格 のカンマ区切りでエントリー価格を上書き")
    # エントリー方式（成行/指値）。上書き価格を使う場合は指値が推奨。
    ap.add_argument("--entry-type", default="成行", help="エントリー方式 (成行/指値)")
    # 30分の手動運用など、JPY/口の目標とロット数を上書きするためのオプション
    ap.add_argument("--per-lot-strong-jpy", type=float, default=None, help="STRONG_GO の利確目標 (JPY/口)")
    ap.add_argument("--per-lot-go-jpy", type=float, default=None, help="GO の利確目標 (JPY/口)")
    ap.add_argument("--lots-strong", type=int, default=None, help="STRONG_GO のロット数を上書き")
    ap.add_argument("--lots-go", type=int, default=None, help="GO のロット数を上書き")
    # 簡易プロフィール: manual30 を指定すると STRONG_GO=1500, GO=800 (JPY/口), ロット=各1 を想定
    ap.add_argument("--profile", default="", help="簡易プロファイル (例: manual30)")
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

    # 正規化された時間足（'240'|'60'|'30'）。"4h+30m" などの複合指定も受け付ける。
    tf_in = (args.tf or "4h").lower().replace(" ", "")
    combo_mode = "+" in tf_in
    TF = "240"
    TF_LOW = None
    if combo_mode:
        hi, lo = tf_in.split("+", 1)
        if hi in ("4h", "240") and lo in ("30m", "30"):
            TF, TF_LOW = "240", "30"
        else:
            # 現状は 4h+30m のみ公式対応。その他は先頭のみ解釈。
            if hi in ("4h", "240"):
                TF = "240"
            elif hi in ("1h", "60"):
                TF = "60"
            elif hi in ("30m", "30"):
                TF = "30"
            combo_mode = False
    else:
        if tf_in in ("4h", "240"):
            TF = "240"
        elif tf_in in ("1h", "60"):
            TF = "60"
        elif tf_in in ("30m", "30"):
            TF = "30"

    # プロファイル/オプションから上書き設定を準備
    per_lot_map = {}
    lots_map = {}
    if args.profile.lower() == "manual30":
        per_lot_map["STRONG_GO"] = 1500.0
        per_lot_map["GO"] = 800.0
        lots_map["STRONG_GO"] = 1
        lots_map["GO"] = 1
    # 個別指定でさらに上書き
    if args.per_lot_strong_jpy is not None:
        per_lot_map["STRONG_GO"] = float(args.per_lot_strong_jpy)
    if args.per_lot_go_jpy is not None:
        per_lot_map["GO"] = float(args.per_lot_go_jpy)
    if args.lots_strong is not None:
        lots_map["STRONG_GO"] = int(args.lots_strong)
    if args.lots_go is not None:
        lots_map["GO"] = int(args.lots_go)

    # エントリー上書きのパース
    entry_override_map = {}
    if args.entry_override:
        for tok in args.entry_override.split(","):
            tok = tok.strip()
            if not tok or "=" not in tok:
                continue
            k, v = tok.split("=", 1)
            try:
                entry_override_map[k.strip().upper()] = float(v.strip())
            except Exception:
                pass

    for sym in instruments:
        try:
            df = None
            source = ""
            df_low = None
            low_source = ""

            def load_df(sym: str, tf_code: str):
                # tf_code: '240'|'60'|'30'
                if tf_code == "240":
                    # 4H優先、なければ60m->4H再サンプリング
                    fp4 = latest_match_for_tf(args.data, sym, "240")
                    if fp4:
                        tmp = pd.read_csv(fp4)
                        if not tmp.empty:
                            dfx = normalize(tmp)
                            src = "4h"
                            if len(dfx) < 80:
                                print(f"[WARN] Not enough bars for {sym} (4h): {len(dfx)}", file=sys.stderr)
                                dfx = None
                        else:
                            print(f"[WARN] Empty CSV for {sym}: {fp4}", file=sys.stderr)
                            dfx = None
                    else:
                        dfx = None
                    if dfx is None:
                        fp60 = latest_match_for_tf(args.data, sym, "60")
                        if not fp60:
                            print(f"[WARN] No CSV for {sym} (4h/60 both missing)", file=sys.stderr)
                            return None, ""
                        d60 = pd.read_csv(fp60)
                        if d60.empty:
                            print(f"[WARN] Empty 60m CSV for {sym}: {fp60}", file=sys.stderr)
                            return None, ""
                        d60 = normalize(d60)
                        dfx = resample_to_4h(d60)
                        src = "60->4h"
                        if len(dfx) < 80:
                            print(f"[WARN] Not enough bars for {sym} after resample (len={len(dfx)})", file=sys.stderr)
                            return None, src
                    return dfx, src
                else:
                    fp = latest_match_for_tf(args.data, sym, tf_code)
                    if not fp:
                        print(f"[WARN] No CSV for {sym} (tf={tf_code})", file=sys.stderr)
                        return None, ""
                    tmp = pd.read_csv(fp)
                    if tmp.empty:
                        print(f"[WARN] Empty CSV for {sym}: {fp}", file=sys.stderr)
                        return None, ""
                    dfx = normalize(tmp)
                    src = ("1h" if tf_code=="60" else "30m")
                    if len(dfx) < 200 and tf_code=="30":
                        print(f"[WARN] Few bars for {sym} (30m len={len(dfx)})", file=sys.stderr)
                    if len(dfx) < 80 and tf_code=="60":
                        print(f"[WARN] Few bars for {sym} (1h len={len(dfx)})", file=sys.stderr)
                    return dfx, src

            if combo_mode:
                # 上位 4h、下位 30m を併用
                df, source = load_df(sym, TF)
                df_low, low_source = load_df(sym, TF_LOW)
                if df is None or df_low is None:
                    continue
                print(f"[INFO] Using combo data for {sym} (hi={source} rows={len(df)}, lo={low_source} rows={len(df_low)})", file=sys.stderr)
                df = indicators(df)
                df_low = indicators(df_low)
                row_hi = df.iloc[-1]
                row_lo = df_low.iloc[-1]
            else:
                # 単一時間足
                df, source = load_df(sym, TF)
                if df is None:
                    continue
                print(f"[INFO] Using {source} data for {sym} (rows={len(df)})", file=sys.stderr)
                df = indicators(df)
                row_hi = df.iloc[-1]

            # エントリー価格の決定（TV価格や手動上書きを考慮）
            price_to_use = None
            # 1) 手動上書きがあれば最優先
            if sym in entry_override_map:
                price_to_use = float(entry_override_map[sym])
                used_source = "override"
            else:
                # 2) TradingView 由来の最新価格があれば採用（複数キー別名も試す）
                tvp = None
                for key in (sym, sym.replace("USD", ""), sym.replace(":", "_")):
                    if tv_prices.get(key) is not None:
                        tvp = tv_prices.get(key)
                        break
                # XAUUSD のみ特例の妥当性チェックを残す
                if sym == "XAUUSD":
                    try:
                        csv_price = float(row_hi["close"])  # コンボ時も上位足の終値を使用
                    except Exception:
                        csv_price = None
                    used_source = "csv"
                    if tvp is not None:
                        # CSVが不正/大きく乖離のときはTV優先
                        if (csv_price is None) or (csv_price < 300 or csv_price > 5000):
                            price_to_use = tvp; used_source = "tradingview"
                        else:
                            try:
                                if abs(csv_price - tvp) / max(tvp, 1e-9) > 0.20:
                                    price_to_use = tvp; used_source = "tradingview"
                            except Exception:
                                pass
                    if price_to_use is None:
                        price_to_use = csv_price
                    print(f"[INFO] XAUUSD price selection: csv={csv_price} tv={tvp} -> used={used_source}", file=sys.stderr)
                else:
                    # 他銘柄は TV 価格があればそれを使う（より即時性が高い前提）
                    if tvp is not None:
                        price_to_use = tvp
                        used_source = "tradingview"

            if args.hold:
                decision = hold_decision(row_hi)
                od = {
                    "instrument": sym,
                    "direction": "-",
                    "signal_rating": None,
                    "decision": decision,
                    "lots": 0,
                    "entry_order": {"type": "-", "price": round_price(sym, row_hi["close"])},
                    "order_type": "-",
                    "ifd_legs": [],
                    "cut_condition": {"sma": "SMA25<SMA75", "macd": "MACD<Signal"}
                }
                orders.append(od)
            else:
                if combo_mode:
                    # 上位足で方向バイアス＆最低限の勢いを確認
                    s_hi = score_entry(row_hi, sym, news_lock=args.newslock)
                    dec_hi = decide_from_score(s_hi, sym)
                    dir_hi = entry_direction(row_hi)
                    # 下位足でエントリータイミングと一致方向を確認
                    s_lo = score_entry(row_lo, sym, news_lock=args.newslock)
                    dec_lo = decide_from_score(s_lo, sym)
                    dir_lo = entry_direction(row_lo)

                    decision = "WAIT"
                    direction = "hold"
                    # 条件: 上位が GO 以上、下位も GO 以上、方向一致
                    if dec_hi in ("GO","STRONG_GO") and dec_lo in ("GO","STRONG_GO") and dir_hi in ("buy","sell") and dir_hi == dir_lo:
                        # 採用は下位足の勢いを優先（STRONG_GO が一つでもあれば STRONG）
                        if "STRONG_GO" in (dec_hi, dec_lo):
                            decision = "STRONG_GO"
                        else:
                            decision = "GO"
                        direction = dir_lo
                        # IFDの距離は per_lot_jpy ベースなので足依存は小さい。トレイリング距離などは下位足ATRを使うため row_lo を渡す。
                        od = build_order(sym, row_lo, decision, direction, price_override=price_to_use,
                                         per_lot_overrides=(per_lot_map or None),
                                         lots_for_map=(lots_map or None),
                                         entry_type=(args.entry_type or "成行"))
                        orders.append(od)
                    else:
                        # 一致しなければWAITを記録（single指定時は後で除外される）
                        od = build_order(sym, row_hi, "WAIT", "hold", price_override=price_to_use,
                                         per_lot_overrides=(per_lot_map or None),
                                         lots_for_map=(lots_map or None),
                                         entry_type=(args.entry_type or "成行"))
                        orders.append(od)
                else:
                    s = score_entry(row_hi, sym, news_lock=args.newslock)
                    decision = decide_from_score(s, sym)
                    direction = entry_direction(row_hi)

                    # 方向が不明ならGO/STRONGを出さない（WAITへ強制）
                    if direction == "hold" and decision != "WAIT":
                        decision = "WAIT"

                    od = build_order(sym, row_hi, decision, direction, price_override=price_to_use,
                                     per_lot_overrides=(per_lot_map or None),
                                     lots_for_map=(lots_map or None),
                                     entry_type=(args.entry_type or "成行"))
                    orders.append(od)

        except Exception as e:
            print(f"[ERROR] {sym}: {e}", file=sys.stderr)
            continue

    # 単方向フィルタ: GO/STRONG_GO & direction in (buy,sell)
    if args.single:
        orders = [o for o in orders if o.get("decision") in ("GO","STRONG_GO") and o.get("direction") in ("buy","sell")]

    # trade_mode 上書き
    # trade_mode 上書き: プロファイルが manual30 で明示指定がなければ DAY30M に設定
    trade_mode = args.trade_mode.strip() or ("DAY30M" if args.profile.lower()=="manual30" else TRADE_MODE)

    payload = {
        "run_id": run_id,
        "capital_jpy": CAPITAL_JPY,
        "per_lot_allocation_jpy": PER_LOT_ALLOCATION_JPY,
        "trade_mode": trade_mode,
        "news_lock": bool(args.newslock),
        "orders": orders,
    }

    # 有効期限（失効タイムスタンプ）を付与（GMO基準: 例 4h など）
    if args.expiry_hours and args.expiry_hours > 0:
        try:
            from datetime import timedelta
            validity_end = datetime.utcnow() + timedelta(hours=args.expiry_hours)
            payload["valid_until"] = validity_end.isoformat() + "Z"
        except Exception:
            pass
    # Persist output JSON and append a short CSV summary for auditing
    try:
        os.makedirs("output", exist_ok=True)
        out_fp = os.path.join("output", f"ifd_{run_id}.json")
        # JSONへは内部スケールのまま保存。表示スケールのメタ情報を添付。
        save_payload = dict(payload)
        try:
            save_payload["display_meta"] = {
                "scale": DISPLAY_SCALE,
                "decimals": DISPLAY_DECIMALS,
            }
            # 各オーダーに表示用価格も添える（互換性のためフィールド追加のみ）
            for od in save_payload.get("orders", []):
                sym = od.get("instrument")
                disp = {}
                try:
                    disp["entry_price"] = display_price(sym, od.get("entry_order", {}).get("price"))
                except Exception:
                    pass
                try:
                    if od.get("ifd_legs"):
                        oco0 = od["ifd_legs"][0].get("oco", {})
                        oco1 = od["ifd_legs"][1].get("oco", {}) if len(od["ifd_legs"])>1 else {}
                        disp["tp1"] = display_price(sym, (oco0.get("take_profit", {}) or {}).get("price"))
                        disp["tp2"] = display_price(sym, (oco1.get("take_profit", {}) or {}).get("price"))
                        disp["sl"]  = display_price(sym, (oco0.get("stop_loss",   {}) or {}).get("price"))
                except Exception:
                    pass
                od["display_prices"] = disp
        except Exception:
            save_payload = payload
        with open(out_fp, "w", encoding="utf-8") as ofh:
            json.dump(save_payload, ofh, ensure_ascii=False, indent=2)
        # Append summary CSV to logs
        os.makedirs("logs", exist_ok=True)
        summary_fn = os.path.join("logs", f"ifd_summary_{datetime.now().strftime('%Y%m%d')}.csv")
        # If file not exists, write header
        write_header = not os.path.exists(summary_fn)
        with open(summary_fn, "a", encoding="utf-8") as sfh:
            if write_header:
                sfh.write("timestamp,run_id,instrument,decision,entry_price_display,lots\n")
            ts = datetime.now().isoformat()
            for od in orders:
                if od.get("entry_order") and isinstance(od["entry_order"], dict):
                    entry_price = od["entry_order"].get("price")
                else:
                    entry_price = ""
                entry_disp = display_price(od.get('instrument'), entry_price) if isinstance(entry_price, (int, float)) else entry_price
                sfh.write(f"{ts},{run_id},{od.get('instrument')},{od.get('decision')},{entry_disp},{od.get('lots')}\n")
        print(f"[INFO] Saved IFD JSON to {out_fp}", file=sys.stderr)
        print(f"[INFO] Appended summary to {summary_fn}", file=sys.stderr)
    except Exception as e:
        print(f"[WARN] Failed to persist IFD output: {e}", file=sys.stderr)

    print_json_and_table(payload)

if __name__ == "__main__":
    main()
