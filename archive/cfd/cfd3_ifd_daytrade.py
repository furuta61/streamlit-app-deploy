#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cfd3_ifd_daytrade.py  (デイトレ用/GMO対応)
- 最新の internal IFD CSV を読み取り、日中デイトレ条件で IFD を生成
- 夜の取引は避ける（JSTの時間帯フィルタ）
- 天然ガスは「大きな STRONG_GO」のみ許可
- TPルール: 基本 STRONG_GO=+3000円、GO=+700〜1500円（日本225基準）
- JSON → Markdown を標準出力に出す（既存フローにそのまま接続可能）

使い方:
  python cfd3_ifd_daytrade.py --once
.env 例:
  MONITOR_IFD_LOGS_DIR=/Users/otomi/Desktop/"vs code"/CFD3_AutoSystem/logs
  DAYTRADE_START_HHMM=0900
  DAYTRADE_END_HHMM=2130
  GAS_MIN_STRONG_SCORE=7
"""

from __future__ import annotations
import os
import sys
import json
from pathlib import Path
from datetime import datetime, time
from typing import Optional, List, Dict, Any
import re

import pandas as pd

# トレンド分析のインポート
try:
    from trend_analyzer import calculate_trend_signals, get_cut_condition
    TREND_ANALYSIS_ENABLED = True
except ImportError:
    TREND_ANALYSIS_ENABLED = False
    print("[WARNING] trend_analyzer.pyが見つかりません。トレンド分析なしで動作します。", file=sys.stderr)

# ====== 環境変数 ======
LOGS_DIR = os.getenv("MONITOR_IFD_LOGS_DIR") or str(Path.home() / 'Desktop' / 'CFD3_AutoSystem' / 'logs')
DAY_START = os.getenv("DAYTRADE_START_HHMM", "0000")  # 24時間取引可能に変更
DAY_END   = os.getenv("DAYTRADE_END_HHMM", "2359")    # 0:00-23:59 = 終日
GAS_MIN_STRONG = float(os.getenv("GAS_MIN_STRONG_SCORE", "0.7"))  # スコアは0-1スケール

CAPITAL_JPY = 1_000_000  # 総資金100万円
PER_LOT     = 300_000    # 1ロットあたり30万円

# ====== 採用銘柄（内部→GMO 表示名マップ）======
# 内部で現れる可能性のある名前を左、GMOでの表示名を右に統一
SYMBOL_MAP = {
    "JP225": "日本225",
    "NQ100": "米国NQ100ミニ",
    "NASDAQ": "米国NQ100ミニ",
    "NASDAQ_MINI": "米国NQ100ミニ",
    "DE40": "ドイツ40",
    "GOLD": "金スポット",
    "GOLD_SPOT": "金スポット",
    "SILVER": "銀スポット",
    "SILVER_SPOT": "銀スポット",
    "NATURAL_GAS": "天然ガス",
    "GAS": "天然ガス",
}

# 今回の採用6銘柄（GMO名で管理）
ALLOWED = {"日本225","米国NQ100ミニ","ドイツ40","金スポット","銀スポット","天然ガス"}

# ====== デイトレ用のTP/SL プリセット ======
# 基本方針:
# - 日本225: STRONG_GO=+3000円, GO=+700〜1500円（中点=1100円をデフォルト）
# - 他銘柄は従来の目安を残しつつ、日中短期向けに狭め設定
#   （必要に応じてここを調整すれば即反映）
TP_SL_TABLE = {
    "日本225": {
        "STRONG_GO": {"tp": 3000, "sl": 1500},
        "GO":        {"tp": 1100, "sl": 1500, "tp_min": 700, "tp_max": 1500},
    },
    "米国NQ100ミニ": {
        "STRONG_GO": {"tp": 300, "sl": 150},
        "GO":        {"tp": 120, "sl": 150},
    },
    "ドイツ40": {
        "STRONG_GO": {"tp": 300, "sl": 150},
        "GO":        {"tp": 120, "sl": 150},
    },
    "金スポット": {
        "STRONG_GO": {"tp": 10.0, "sl": 10.0},  # $10
        "GO":        {"tp": 7.0,  "sl": 10.0},  # $7
    },
    "銀スポット": {
        "STRONG_GO": {"tp": 0.40, "sl": 0.30},  # $0.40
        "GO":        {"tp": 0.25, "sl": 0.30},  # $0.25
    },
    "天然ガス": {
        "STRONG_GO": {"tp": 0.20, "sl": 0.15},  # US$ 指値の目安（高ボラのため浅すぎない）
        "GO":        {"tp": None, "sl": None},  # GOは原則エントリーしない（制限）
    }
}

# ロット数（デイトレは控えめ）
LOTS = {"GO": 4, "STRONG_GO": 6}

def _to_jst(dt: pd.Timestamp) -> pd.Timestamp:
    # ログ側がJST前提ならそのまま、UTCならJSTへ変換…だがCSVのタイムゾーンまちまちなので
    # ここでは naive をそのままJST扱い、tz-awareならJSTへ
    if dt.tzinfo is None:
        return dt
    return dt.tz_convert("Asia/Tokyo").tz_localize(None)

def _hhmm_to_time(s: str) -> time:
    s = s.strip().replace(":", "")
    hh = int(s[:2]); mm = int(s[2:])
    return time(hh, mm)

def in_day_window(ts: pd.Timestamp) -> bool:
    j = _to_jst(pd.to_datetime(ts))
    t = j.time()
    start = _hhmm_to_time(DAY_START)
    end   = _hhmm_to_time(DAY_END)
    return (t >= start) and (t <= end)

def find_latest_internal_ifd(logs_dir: Path) -> Optional[Path]:
    """最新のinternal CSV/ifd_summaryファイルを取得。

    選定ルール（優先順）:
    1) `events_scored_*_internal.csv` または `ifd_summary_*.csv` のうち、最終更新が環境変数
       `IFD_FILE_MAX_AGE_MINUTES` (デフォルト120分)以内で、かつ 'entry' と 'signal' を持ち、
       'entry_source' または 'instrument' が存在し、かつ entry 列に実データがあるファイルを選ぶ
    2) 条件を満たすファイルが無ければ最新ファイルをフォールバックとして返す（警告表示）
    """
    import csv, time
    # 検索対象: internal と ifd_summary
    candidates = list(Path(logs_dir).glob('events_scored_*_internal.csv')) + list(Path(logs_dir).glob('ifd_summary_*.csv'))
    candidates = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        print(f"[ERROR] CSVファイルが見つかりません: {logs_dir}/events_scored_*_internal.csv", file=sys.stderr)
        return None

    # デフォルトを120分から60分に変更（運用での誤選択を減らす）
    max_age_min = int(os.getenv('IFD_FILE_MAX_AGE_MINUTES', '60'))

    for p in candidates:
        try:
            with open(p, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                header = [h.strip().lower() for h in header]
                header_set = set(header)

                # 必要列が揃っているか
                if not ({'entry', 'signal'}.issubset(header_set) and (('entry_source' in header_set) or ('instrument' in header_set))):
                    continue

                # entry 列に非空データが存在するかをチェック（最初の50行まで）
                entry_idx = header.index('entry') if 'entry' in header else None
                has_entry = False
                for i, row in enumerate(reader):
                    if entry_idx is not None and len(row) > entry_idx:
                        val = row[entry_idx]
                        if val is not None and str(val).strip() not in ('', 'nan', 'NaN'):
                            has_entry = True
                            break
                    if i >= 50:
                        break
                if not has_entry:
                    continue

        except Exception:
            # 読めない/破損したファイルは飛ばす
            continue

        # 年齢チェック
        file_age_minutes = (time.time() - p.stat().st_mtime) / 60
        if file_age_minutes > max_age_min:
            print(f"[DEBUG] スキップ (古すぎる): {p.name} ({file_age_minutes:.1f}分前) > {max_age_min}分", file=sys.stderr)
            continue

        print(f"[INFO] 使用CSV: {p.name} ({file_age_minutes:.1f}分前)", file=sys.stderr)
        return p

    # フィルタを通るファイルがない場合は最新ファイルをフォールバック
    latest = candidates[0]
    file_age_minutes = (time.time() - latest.stat().st_mtime) / 60
    print(f"[WARNING] 条件を満たすinternal/ifd_summaryファイルが見つかりませんでした。フォールバックで最新ファイルを使用します: {latest.name} ({file_age_minutes:.1f}分前)", file=sys.stderr)
    return latest

def load_rows(p: Path) -> pd.DataFrame:
    df = pd.read_csv(p)
    # 正規化: 列名が様々でも拾えるように
    # 必要列: date/time, instrument/entry_source, type/decision, combined_score/score, entry, signal (direction)
    
    # signalカラム(BUY/SELL)をdirectionとして使う
    if 'signal' in df.columns and 'direction' not in df.columns:
        df['direction'] = df['signal']
    
    # combined_scoreをscoreとしても使えるように
    if 'combined_score' in df.columns and 'score' not in df.columns:
        df['score'] = df['combined_score']
    
    # typeカラムが無い場合、combined_scoreから推測
    if 'type' not in df.columns:
        if 'combined_score' in df.columns:
            df['type'] = df['combined_score'].apply(lambda x: 'STRONG_GO' if x >= 0.85 else ('GO' if x >= 0.82 else 'HOLD'))
    else:
        # type列があるが、NaN値がある場合はcombined_scoreから補完
        if 'combined_score' in df.columns:
            mask = df['type'].isna()
            df.loc[mask, 'type'] = df.loc[mask, 'combined_score'].apply(
                lambda x: 'STRONG_GO' if x >= 0.85 else ('GO' if x >= 0.82 else 'HOLD')
            )
    
    # decisionがあればtypeにコピー
    if 'decision' in df.columns:
        mask = df['type'].isna()
        df.loc[mask, 'type'] = df.loc[mask, 'decision']
    
    return df

def normalize_symbol(sym: Any) -> Optional[str]:
    if sym is None or (isinstance(sym, float) and pd.isna(sym)):
        return None
    s = str(sym).strip()
    s2 = SYMBOL_MAP.get(s.upper(), s)
    return s2 if s2 in ALLOWED else None

def choose_tp_sl(symbol: str, decision: str, entry: float) -> tuple[float, float, Optional[float]]:
    """
    returns (tp, sl, trail_distance or None)
    """
    table = TP_SL_TABLE.get(symbol, {})
    dkey = "STRONG_GO" if decision == "STRONG_GO" else "GO"
    spec = table.get(dkey, {})
    tp = spec.get("tp")
    sl = spec.get("sl")
    # 日本225のGOは 700〜1500 の範囲に収める
    if symbol == "日本225" and dkey == "GO" and tp is not None:
        tp_min = spec.get("tp_min", 700)
        tp_max = spec.get("tp_max", 1500)
        tp = max(tp_min, min(tp, tp_max))
    trail = {
        "日本225": 300,
        "米国NQ100ミニ": 120,
        "ドイツ40": 120,
        "金スポット": 3.0,
        "銀スポット": 0.10,
        "天然ガス": 0.05,
    }.get(symbol, None)
    return tp, sl, trail

def build_ifd_rows(df: pd.DataFrame) -> List[Dict[str,Any]]:
    out: List[Dict[str,Any]] = []
    now_jst = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # トレンド分析結果をキャッシュ
    trend_cache = {}
    
    for _, r in df.iterrows():
        raw_sym = r.get("entry_source") or r.get("instrument")
        # フォールバック: entry_source が無ければ text 列にある末尾の [SYMBOL] を抽出する
        if not raw_sym:
            txt = r.get('text') or ''
            if isinstance(txt, str):
                m = re.search(r"\[([^\]]+)\]", txt)
                if m:
                    raw_sym = m.group(1)
        sym = normalize_symbol(raw_sym)
        if not sym:
            print(f"[DEBUG] スキップ (normalize失敗): raw_sym={raw_sym}", file=sys.stderr)
            continue

        # 夜回避: 日中ウィンドウ外はスキップ
        ts = r.get("date") or r.get("datetime")
        if pd.isna(ts):
            # タイムスタンプ不明は念のため除外
            print(f"[DEBUG] スキップ (タイムスタンプ不明): sym={sym}", file=sys.stderr)
            continue
        if not in_day_window(pd.to_datetime(ts)):
            print(f"[DEBUG] スキップ (日中ウィンドウ外): sym={sym}, ts={ts}", file=sys.stderr)
            continue

        # 判定
        decision = str(r.get("type") or "").upper()
        if decision not in ("GO","STRONG_GO"):
            print(f"[DEBUG] スキップ (decision不正): sym={sym}, decision={decision}", file=sys.stderr)
            continue

        # 天然ガスは「大きな STRONG_GO」以外は不参加
        if sym == "天然ガス":
            score = float(r.get("combined_score") or r.get("score") or 0.0)
            if decision != "STRONG_GO" or score < GAS_MIN_STRONG:
                continue

        # 🆕 トレンド分析による方向判定（トレンドを最優先）
        direction = str(r.get("direction") or "buy").lower()
        
        if TREND_ANALYSIS_ENABLED:
            # SYMBOL_MAPの逆引き（GMO名 → yfinance symbol用）
            symbol_key = None
            for k, v in SYMBOL_MAP.items():
                if v == sym:
                    symbol_key = k
                    break
            
            # デイトレ用: 短期トレンドを優先して取得（アンサンブル: 15m + 5m）
            # 環境変数で上書き可能:
            #   DAY_TREND_PERIOD_15M (例 '14d'), DAY_TREND_PERIOD_5M (例 '5d')
            #   DAY_TREND_INTERVAL_PRIMARY (default '15m'), DAY_TREND_INTERVAL_SECONDARY (default '5m')
            day_period_p = os.getenv('DAY_TREND_PERIOD_15M', os.getenv('DAY_TREND_PERIOD', '14d'))
            day_period_s = os.getenv('DAY_TREND_PERIOD_5M', os.getenv('DAY_TREND_PERIOD', '5d'))
            day_interval_p = os.getenv('DAY_TREND_INTERVAL_PRIMARY', '15m')
            day_interval_s = os.getenv('DAY_TREND_INTERVAL_SECONDARY', '5m')
            ensemble_threshold = float(os.getenv('DAY_TREND_THRESHOLD', '0.65'))

            # cache keys per symbol and interval
            cache_key_p = f"{symbol_key}:{day_interval_p}:{day_period_p}"
            cache_key_s = f"{symbol_key}:{day_interval_s}:{day_period_s}"

            if symbol_key and cache_key_p not in trend_cache:
                try:
                    print(f"[TREND] {sym} 短期(主)分析... (period={day_period_p}, interval={day_interval_p})", file=sys.stderr)
                    trend_cache[cache_key_p] = calculate_trend_signals(symbol_key, period=day_period_p, interval=day_interval_p)
                except Exception as e:
                    print(f"[TREND] 主分析失敗 {sym}: {e}", file=sys.stderr)
                    trend_cache[cache_key_p] = None

            if symbol_key and cache_key_s not in trend_cache:
                try:
                    print(f"[TREND] {sym} 短期(副)分析... (period={day_period_s}, interval={day_interval_s})", file=sys.stderr)
                    trend_cache[cache_key_s] = calculate_trend_signals(symbol_key, period=day_period_s, interval=day_interval_s)
                except Exception as e:
                    print(f"[TREND] 副分析失敗 {sym}: {e}", file=sys.stderr)
                    trend_cache[cache_key_s] = None

            trend_p = trend_cache.get(cache_key_p)
            trend_s = trend_cache.get(cache_key_s)

            # 両方が取得でき、方向が一致し、強度が閾値以上で採用
            if not trend_p or not trend_s:
                print(f"[TREND] {sym}: 十分なトレンドデータなし (主={bool(trend_p)}, 副={bool(trend_s)}) - スキップ", file=sys.stderr)
                continue

            dir_p = trend_p.get('direction')
            dir_s = trend_s.get('direction')
            str_p = float(trend_p.get('strength', 0.0))
            str_s = float(trend_s.get('strength', 0.0))

            if dir_p == dir_s and str_p >= ensemble_threshold and str_s >= ensemble_threshold:
                if dir_p == 'BUY':
                    direction = 'buy'
                    print(f"[TREND] {sym}: 両インターバルで買い合意 (主{str_p:.2f}, 副{str_s:.2f}) → 買いIFD生成", file=sys.stderr)
                elif dir_p == 'SELL':
                    direction = 'sell'
                    print(f"[TREND] {sym}: 両インターバルで売り合意 (主{str_p:.2f}, 副{str_s:.2f}) → 売りIFD生成", file=sys.stderr)
                else:
                    print(f"[TREND] {sym}: 合意方向中立 - スキップ", file=sys.stderr)
                    continue
            else:
                print(f"[TREND] {sym}: アンサンブル不一致または強度不足 (主={dir_p}/{str_p:.2f}, 副={dir_s}/{str_s:.2f}) - スキップ", file=sys.stderr)
                continue
        
        entry = r.get("entry")
        if entry is None or pd.isna(entry):
            continue
        entry = float(entry)

        # 価格距離（TP/SL）決定
        tp_dist, sl_dist, trail_dist = choose_tp_sl(sym, decision, entry)
        if tp_dist is None or sl_dist is None:
            # 設定が無い（=参加しない）
            continue

        # 指値価格の生成
        if direction == "buy":
            tp = entry + tp_dist
            sl = entry - sl_dist
        else:
            tp = entry - tp_dist
            sl = entry + sl_dist

        lots = LOTS.get(decision, 4)
        
        # 🆕 CUT条件をトレンド分析から取得
        cut_condition_text = "SMA25<SMA75 or MACD<Signal"  # デフォルト
        if TREND_ANALYSIS_ENABLED and symbol_key and symbol_key in trend_cache:
            trend = trend_cache[symbol_key]
            cut_condition_text = get_cut_condition(trend['direction'], trend['sma_signal'], trend['macd_signal'])

        # エントリー方式の優先設定: 環境変数 PREFER_IFD=1 を設定すると指値(IFD)優先
        prefer_ifd = os.getenv('PREFER_IFD', '0').lower() not in ('0', 'false', 'no')
        # デフォルト挙動: STRONG_GO -> 成行、GO -> 指値
        if prefer_ifd:
            # 指値(IFD)優先: すべて指値で作成（ユーザーがIFDの精度を評価したい場合に有効）
            entry_order_type = "limit"
        else:
            entry_order_type = "market" if decision == "STRONG_GO" else "limit"

        order_type_display = "成行" if entry_order_type == "market" else "指値"

        order = {
            "instrument": sym,
            "direction": direction,
            "signal_rating": float(r.get("combined_score") or r.get("score") or 0.0),
            "decision": decision,
            "lots": lots,
            # priceはCSV兼用の近似値として常に保持する（成行でも参照しやすく）
            "entry_order": {"type": entry_order_type, "price": round(entry, 2 if sym in ("金スポット","銀スポット","天然ガス") else 1)},
            "order_type": order_type_display,
            "ifd_legs": [
                {"name": "IFD-1", "oco": {
                    "take_profit": {"price": round(tp, 2 if sym in ("金スポット","銀スポット","天然ガス") else 1)},
                    "stop_loss":   {"price": round(sl, 2 if sym in ("金スポット","銀スポット","天然ガス") else 1)}
                }}
            ],
            "cut_condition": {"sma": cut_condition_text, "macd": cut_condition_text},
            "timestamp": now_jst
        }
        if trail_dist is not None:
            order["ifd_legs"].append(
                {"name":"IFD-2","oco":{
                    "take_profit":{"price": round(tp, 2 if sym in ("金スポット","銀スポット","天然ガス") else 1)},
                    "stop_loss":  {"price": round(sl, 2 if sym in ("金スポット","銀スポット","天然ガス") else 1)},
                    "trailing_stop":{"activate_after": round(tp, 2 if sym in ("金スポット","銀スポット","天然ガス") else 1),
                                     "distance": trail_dist}
                }}
            )
        out.append(order)
    return out

def main():
    p = find_latest_internal_ifd(Path(LOGS_DIR))
    if not p:
        print("{}", end="")
        return
    df = load_rows(p)

    # フィルタ後の IFD 注文を構築
    orders = build_ifd_rows(df)

    result = {
        "run_id": datetime.now().strftime("%Y-%m-%d-%H%M"),
        "capital_jpy": CAPITAL_JPY,
        "per_lot_allocation_jpy": PER_LOT,
        "trade_mode": "DAYTRADE",
        "orders": orders
    }

    # === CSV出力（continuous_monitor.py用）===
    now_str = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = Path(LOGS_DIR) / f"events_scored_{now_str}_internal.csv"
    
    # OrdersをCSV形式に変換
    csv_rows = []
    for o in orders:
        csv_rows.append({
            'text': f"Auto IFD - {o['instrument']}",
            'date': o['timestamp'],
            'combined_score': o['signal_rating'],
            'signal': o['direction'].upper(),
            'entry': o['entry_order']['price'],
            'TP': o['ifd_legs'][0]['oco']['take_profit']['price'],
            'SL': o['ifd_legs'][0]['oco']['stop_loss']['price'],
            'entry_source': o['instrument'],
            'lot_size': o['lots'],
            'risk_amount': abs(o['entry_order']['price'] - o['ifd_legs'][0]['oco']['stop_loss']['price']) * o['lots'] * 100,
            'auto_tp_applied': False,
            'auto_tp_reason': '',
            'direction': o['direction']  # 🆕 方向を追加
        })
    
    if csv_rows:
        csv_df = pd.DataFrame(csv_rows)
        csv_df.to_csv(csv_path, index=False)
        print(f"\n✅ CSV出力: {csv_path}", file=sys.stderr)

    # === JSON 出力 ===
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # === Markdown 出力（人間可読）===
    # シンプル8項目: 銘柄 推奨度 方向 エントリー方法 価格 TP SL ロット
    rows = []
    for o in orders:
        tp = o["ifd_legs"][0]["oco"]["take_profit"]["price"]
        sl = o["ifd_legs"][0]["oco"]["stop_loss"]["price"]
        entry_price = o["entry_order"]["price"]
        
        # 推奨度: STRONG_GO=★5 STRONG GO, GO=★4 GO
        rating = "★5 STRONG GO" if o["decision"]=="STRONG_GO" else "★4 GO"
        
        # 方向表示（日本語、見やすく）
        direction_map = {"buy": "🟢 買", "sell": "🔴 売"}
        dir_display = direction_map.get(o["direction"], o["direction"].upper())
        
        # エントリー方法: STRONG_GO=成行, GO=指値（デイトレの基本戦略）
        entry_method = "成行" if o["decision"]=="STRONG_GO" else "指値"
        
        rows.append([
            o["instrument"],      # 1. 銘柄
            rating,               # 2. 推奨度
            dir_display,          # 3. 方向（🟢買/🔴売）
            entry_method,         # 4. エントリー方法
            entry_price,          # 5. 価格
            tp,                   # 6. TP
            sl,                   # 7. SL
            o["lots"]             # 8. ロット
        ])

    # シンプルなMarkdownテーブル（8項目）
    md = [
        "",
        "| 銘柄 | 推奨度 | 方向 | エントリー方法 | 価格 | TP | SL | ロット |",
        "|---|:---:|:---:|:---:|---:|---:|---:|:---:|"
    ]
    for r in rows:
        md.append("| " + " | ".join(str(x) for x in r) + " |")
    print("\n".join(md))

if __name__ == "__main__":
    main()
