#!/usr/bin/env python3
"""
mygpt_strategy.py
CFD3 Pro System — Adaptive TP/SL (%-based)
© 2025 OTOMI CFD3_AutoSystem
"""

import json
import os
from datetime import datetime
import requests
from typing import Dict, List

# ==============================
# ニュース + テクニカル複合判定設定
# ==============================
def _get_float_env(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        return float(v) if v is not None and v != "" else default
    except Exception:
        return default

# 判定重み（環境変数で上書き可）
TECH_WEIGHT = _get_float_env("TECH_WEIGHT", 0.6)
NEWS_WEIGHT = _get_float_env("NEWS_WEIGHT", 0.4)

# 判定閾値（環境変数で上書き可）
GO_THRESHOLD = _get_float_env("GO_THRESHOLD", 3.8)
STRONG_GO_THRESHOLD = _get_float_env("STRONG_GO_THRESHOLD", 5.5)

# ニュースAPI（例: Google News RSS 検索を利用）
NEWS_SOURCES = [
    "https://news.google.com/rss/search?q=日銀+政策",
    "https://news.google.com/rss/search?q=FOMC",
    "https://news.google.com/rss/search?q=米国+雇用統計",
    "https://news.google.com/rss/search?q=インフレ率",
    "https://news.google.com/rss/search?q=地政学+リスク",
]


def fetch_latest_news(limit: int = 5) -> List[str]:
    headlines: List[str] = []
    for src in NEWS_SOURCES:
        try:
            r = requests.get(src, timeout=5)
            if r.status_code == 200 and "<title>" in r.text:
                titles = [t.split("</title>")[0].split("<title>")[-1] for t in r.text.split("<title>")[1:]]
                for t in titles:
                    if "Google" in t or "ニュース" in t:
                        continue
                    headlines.append(t.strip())
        except Exception:
            continue
    return headlines[:limit]


def analyze_news_impact(headlines: List[str]) -> Dict[str, object]:
    """簡易スコアリング: 重要ワードを含むニュースで加減点"""
    score = 0.0
    matched: List[str] = []
    for title in headlines:
        low = title.lower()
        if any(k in low for k in ["利上げ", "利下げ", "金融緩和", "金利据え置き"]):
            score += 1.0
            matched.append(title)
        elif any(k in low for k in ["インフレ", "消費者物価", "cpi", "物価上昇"]):
            score += 0.5
            matched.append(title)
        elif any(k in low for k in ["雇用統計", "fomc", "frb", "景気後退"]):
            score += 1.5
            matched.append(title)
        elif any(k in low for k in ["地政学", "紛争", "戦争", "攻撃"]):
            score -= 1.0
            matched.append(title)
    return {"score": score, "matched": matched[:3]}


def analyze_technicals(data: Dict) -> float:
    """
    テクニカルスコア算出
    
    TradingViewシグナルを「参考値」として扱い、後段のニュース・変動率・RSI等と
    組み合わせることで独自の判断を行う。
    
    スコアリング（10点満点）:
    - STRONG_GO: 7.0点 → 有力だが、ニュース等で補強が必要
    - GO: 5.5点 → 中程度、他要素次第
    - WAIT: 3.0点 → 様子見推奨
    
    このスコア単体では判定せず、NEWS/RSI/変動率と合算して最終判断する。
    """
    signal = data.get("signal", "").upper()
    
    if signal == "STRONG_GO":
        return 7.0  # 有力だが単体では不十分
    elif signal == "GO":
        return 5.5  # 中程度
    elif signal == "WAIT":
        return 3.0  # 様子見
    else:
        return 4.0  # 不明


def _extract_change_pct(screener: Dict | None, data: Dict | None) -> float | None:
    """screener または data から変動率(%)を推定して返す。見つからなければ None。
    対応キー例: change, Change, change_pct, percent, Percent, 1d_change など。
    値は 5.0 なら +5%、-3.2 なら -3.2% を意味。
    """
    cand_keys = [
        "change_pct", "ChangePct", "percent", "Percent",
        "change", "Change", "1d_change", "1DChange"
    ]
    src_list = [screener or {}, data or {}]
    for src in src_list:
        if not isinstance(src, dict):
            continue
        for k in cand_keys:
            if k in src:
                try:
                    val = src[k]
                    # 一部APIは 0.05 (=5%) で返す可能性もあるので 1未満は%に換算
                    f = float(val)
                    if abs(f) < 1.0:
                        f *= 100.0
                    return f
                except Exception:
                    continue
    return None


def _extreme_move_adjustment(change_pct: float | None) -> float:
    """大幅変動ボーナスを返す。環境変数で閾値・加点を調整可。
    既定: 2%→+0.3, 3%→+0.5, 5%→+1.0（絶対値ベース）
    """
    on = os.getenv("EXTREME_MOVE_ON", "1") in ("1", "true", "True")
    if not on or change_pct is None:
        return 0.0
    # thresholds
    s1 = _get_float_env("EXTREME_MOVE_STEP1", 2.0)
    s2 = _get_float_env("EXTREME_MOVE_STEP2", 3.0)
    s3 = _get_float_env("EXTREME_MOVE_STEP3", 5.0)
    # adjustments
    a1 = _get_float_env("EXTREME_MOVE_ADJ1", 0.3)
    a2 = _get_float_env("EXTREME_MOVE_ADJ2", 0.5)
    a3 = _get_float_env("EXTREME_MOVE_ADJ3", 1.0)

    m = abs(change_pct)
    if m >= s3:
        return a3
    if m >= s2:
        return a2
    if m >= s1:
        return a1
    return 0.0


def analyze_signal(symbol: str, data: Dict) -> Dict[str, object]:
    """ニュース + テクニカルの複合分析: signal_monitor から呼び出す想定

    優先度:
      1) data に `news_items` / `sentiment_score` があればそれを用いる（news_collector の結果）。
      2) 無ければ簡易 RSS ベースの `fetch_latest_news()` にフォールバック。

    さらに、`screener` 情報があれば RSI/Recommend で補正します。
    """
    tech_score = analyze_technicals(data)

    # --- ニュース由来スコアの決定 ---
    news_refs: List[str] = []
    news_score_calc = 0.0
    if isinstance(data, dict) and ("news_items" in data or "sentiment_score" in data):
        try:
            items = data.get("news_items") or []
            if isinstance(items, list):
                # 件数ベース: 0..(>=10) を 0..1 に正規化（最大1.0）
                density = min(len(items) / 10.0, 1.0)
            else:
                density = 0.0
            # センチメント（-1..1 を -1..1 にクリップ）
            try:
                sent = float(data.get("sentiment_score", 0.0) or 0.0)
            except Exception:
                sent = 0.0
            sent = max(min(sent, 1.0), -1.0)

            # 合成: 件数 2.0 点 + センチメント 1.5 点（合計 -1.5..3.5 程度）
            sentiment_weight = _get_float_env("SENTIMENT_LOCAL_WEIGHT", 1.5)
            news_score_calc = 2.0 * density + sentiment_weight * sent
            # 参照タイトル（上位3件）
            try:
                news_refs = [
                    (it.get("title") if isinstance(it, dict) else str(it))
                    for it in items
                ][:3]
            except Exception:
                news_refs = []
        except Exception:
            # フォールバック
            headlines = fetch_latest_news()
            news_result = analyze_news_impact(headlines)
            news_score_calc = float(news_result.get("score", 0.0) or 0.0)
            news_refs = list(news_result.get("matched", []) or [])
    else:
        # 旧来の簡易 RSS ベース
        headlines = fetch_latest_news()
        news_result = analyze_news_impact(headlines)
        news_score_calc = float(news_result.get("score", 0.0) or 0.0)
        news_refs = list(news_result.get("matched", []) or [])

    total = tech_score * TECH_WEIGHT + news_score_calc * NEWS_WEIGHT

    # --- Screener 補正 ---
    adj = 0.0
    screener = None
    if isinstance(data, dict):
        screener = data.get("screener") or data.get("meta") or None
    if screener and isinstance(screener, dict):
        try:
            rsi = float(screener.get("RSI") or screener.get("rsi") or 50)
        except Exception:
            rsi = 50
        recommend = screener.get("Recommend") or screener.get("recommend") or "NEUTRAL"

        # RSI adjustments (overbought/oversold)
        if rsi > 70:
            adj -= 1.0
        elif rsi < 30:
            adj += 1.0

        # TradingView/YF recommend adjustments
        if recommend == "STRONG_BUY":
            adj += 0.5
        elif recommend == "STRONG_SELL":
            adj -= 0.5

    # 大幅変動ボーナス
    try:
        change_pct = _extract_change_pct(screener, data)
        move_adj = _extreme_move_adjustment(change_pct)
        adj += move_adj
    except Exception:
        pass

    adjusted = total + adj

    decision = "WAIT"
    if adjusted >= STRONG_GO_THRESHOLD:
        decision = "STRONG_GO"
    elif adjusted >= GO_THRESHOLD:
        decision = "GO"

    # 売買方向の決定（screener の Recommend/RSI/変動率から推定）
    side = "BUY"  # デフォルト
    if screener and isinstance(screener, dict):
        rec = screener.get("Recommend") or screener.get("recommend") or ""
        try:
            rsi_val = float(screener.get("RSI") or screener.get("rsi") or 50)
        except Exception:
            rsi_val = 50
        # 変動率（負=下落、正=上昇）
        change_pct_val = _extract_change_pct(screener, data)

        # 判定ロジック: 優先順位
        # 1. Recommend が SELL 系 → SELL
        if "SELL" in rec.upper():
            side = "SELL"
        # 2. RSI > 70 (過熱) かつ 上昇変動 → SELL
        elif rsi_val > 70 and change_pct_val and change_pct_val > 0:
            side = "SELL"
        # 3. 大幅下落（change_pct < -3%）かつ RSI < 40 → BUY（押し目買い）
        elif change_pct_val and change_pct_val < -3.0 and rsi_val < 40:
            side = "BUY"
        # 4. Recommend が BUY 系 → BUY
        elif "BUY" in rec.upper():
            side = "BUY"
        # 5. RSI < 30 (売られ過ぎ) → BUY
        elif rsi_val < 30:
            side = "BUY"
        # デフォルトは現状 GO/STRONG_GO → BUY、WAIT 含め中立は BUY 方向

    return {
        "symbol": symbol,
        "decision": decision,
        "side": side,
        "rating": round(adjusted, 2),
        "rating_adjustment": round(adj, 2),
        "news_score": round(news_score_calc, 2),
        "tech_score": round(tech_score, 2),
        "news_refs": news_refs,
        "timestamp": datetime.utcnow().isoformat(),
    }


# シンボルごとのTP/SL比率設定（％）
TP_SL_RATES = {
    "JP225": {"tp": 0.023, "sl": 0.010},
    "NQ100": {"tp": 0.020, "sl": 0.010},
    "XAUUSD": {"tp": 0.015, "sl": 0.008},
    "XAGUSD": {"tp": 0.025, "sl": 0.012},
    "NGAS": {"tp": 0.030, "sl": 0.015},
    "GER40": {"tp": 0.018, "sl": 0.009},
    # US30 (Dow Jones) - default provisional ratios: TP +2.0%, SL -1.0%
    # You can change these by editing TP_SL_RATES or setting env overrides in future.
    "US30": {"tp": 0.020, "sl": 0.010},
}

# 桁設定（整数 or 小数点）
ROUND_DIGITS = {
    "JP225": 0,
    "NQ100": 0,
    "GER40": 0,
    "XAUUSD": 2,
    "XAGUSD": 2,
    "NGAS": 3,
    # US30 displayed as integer by default
    "US30": 0,
}

OUTPUT_PATH = "output/ifd_orders.jsonl"

# 想定価格レンジ（簡易） - エラー防止と極端値検出のため
PRICE_RANGES = {
    "JP225": (10000, 70000),
    "NQ100": (5000, 40000),
    "XAUUSD": (300, 5000),
    "XAGUSD": (5, 200),
    "NGAS": (0.1, 30),
    "GER40": (5000, 40000),
    # US30 (Dow Jones) expected range
    "US30": (10000, 70000),
}

# TP/SL の上限倍率（entry に対する最大倍率）
MAX_TP_MULTIPLIER = 5.0
MIN_SL_MULTIPLIER = 0.01

# デフォルト注文数量（CFD や口数の目安）
DEFAULT_QTY = {
    "JP225": 1,
    "NQ100": 1,
    "XAUUSD": 1,
    "XAGUSD": 10,
    "NGAS": 5,
    "GER40": 1,
    # US30 default lot/qty
    "US30": 1,
}


def rating_to_recommendation(rating: float | None, decision: str) -> str:
    """数値 rating があれば閾値で推奨度を返す。なければ decision ベースで推定する。"""
    try:
        if rating is not None:
            r = float(rating)
            if r >= 6.0:
                return "STRONG_BUY"
            if r >= 4.0:
                return "BUY"
            if r >= 2.0:
                return "NEUTRAL"
            if r >= 0.0:
                return "SELL"
            return "STRONG_SELL"
    except Exception:
        pass
    # fallback to decision mapping
    if decision == "STRONG_GO":
        return "STRONG_BUY"
    if decision == "GO":
        return "BUY"
    if decision == "WAIT":
        return "HOLD"
    return "NEUTRAL"

def generate_ifd(symbol: str, entry_price: float, decision="STRONG_GO", meta: Dict = None, side: str = None, qty: float = None):
    """Calculate IFD (take profit / stop loss) for a symbol based on % rules
    
    If side="SELL", TP/SL are inverted (entry > TP, entry < SL).
    """
    if symbol not in TP_SL_RATES:
        raise ValueError(f"Unsupported symbol: {symbol}")

    rates = TP_SL_RATES[symbol]
    rd = ROUND_DIGITS.get(symbol, 2)

    if entry_price <= 0:
        raise ValueError("Invalid entry price")

    # basic sanity: entry price within expected range
    if symbol in PRICE_RANGES:
        lo, hi = PRICE_RANGES[symbol]
        if not (lo <= entry_price <= hi):
            raise ValueError(f"Entry price {entry_price} for {symbol} outside expected range [{lo},{hi}]")

    # determine side by decision if not provided
    if not side:
        # fallback: if meta has 'side' use it, else default to BUY
        if meta and isinstance(meta, dict):
            side = meta.get("side", "BUY")
        else:
            side = "BUY"

    # calculate TP/SL based on side
    if side == "SELL":
        # SELL: entry > TP (profit at lower price), entry < SL (loss at higher price)
        tp = round(entry_price * (1 - rates["tp"]), rd)  # lower
        sl = round(entry_price * (1 + abs(rates["sl"])), rd)  # higher
    else:
        # BUY: entry < TP (profit at higher price), entry > SL (loss at lower price)
        tp = round(entry_price * (1 + rates["tp"]), rd)
        sl = round(entry_price * (1 - abs(rates["sl"])), rd)

    # 安全チェック（BUY/SELL 両対応）
    if side == "BUY":
        if tp <= entry_price or sl >= entry_price:
            raise ValueError(f"Abnormal BUY TP/SL detected for {symbol}: TP={tp}, SL={sl}, entry={entry_price}")
    else:
        if tp >= entry_price or sl <= entry_price:
            raise ValueError(f"Abnormal SELL TP/SL detected for {symbol}: TP={tp}, SL={sl}, entry={entry_price}")

    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "symbol": symbol,
        "decision": decision,
        "side": side,
        "entry_price": entry_price,
        "take_profit": tp,
        "stop_loss": sl,
    }

    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "symbol": symbol,
        "decision": decision,
        "side": side,
        "entry_price": entry_price,
        "take_profit": tp,
        "stop_loss": sl,
    }

    # determine qty default
    if qty is None:
        qty = DEFAULT_QTY.get(symbol, 1)
    result["qty"] = qty

    # attach optional metadata (rating, news_refs, etc.)
    if meta and isinstance(meta, dict):
        for k, v in meta.items():
            # avoid overwriting core keys
            if k not in result:
                result[k] = v
        # keep a small, explicit trace of the original incoming webhook/payload
        # without clobbering core keys. This helps post-mortem debugging.
        try:
            if 'signal' in meta:
                result['original_signal'] = meta.get('signal')
            if 'time' in meta:
                result['incoming_ts'] = meta.get('time')
            elif 'timestamp' in meta:
                result.setdefault('incoming_ts', meta.get('timestamp'))
            # store a compact snapshot if present (avoid huge objects)
            if 'payload' in meta:
                result['incoming_payload'] = meta.get('payload')
            else:
                # if meta seems to be the incoming payload itself, store a trimmed copy
                # keep only a few keys to avoid overly large IFD lines
                keys_of_interest = ['symbol', 'price', 'signal', 'time']
                small = {k: meta.get(k) for k in keys_of_interest if k in meta}
                if small:
                    result.setdefault('incoming_payload', small)
        except Exception:
            # defensive: never fail IFD generation because of metadata issues
            pass

    # Normalize and guarantee fields for downstream clarity
    # rating: prefer explicit meta rating if present
    rating_val = None
    try:
        if isinstance(meta, dict):
            rating_val = meta.get("rating") or meta.get("final_rating")
    except Exception:
        rating_val = None
    # Ensure news-related fields exist
    result.setdefault("news_refs", meta.get("news_refs") if isinstance(meta, dict) else [])
    result.setdefault("news_count", int(meta.get("news_count") if isinstance(meta, dict) and meta.get("news_count") is not None else 0))
    result.setdefault("sentiment_score", float(meta.get("sentiment_score") if isinstance(meta, dict) and meta.get("sentiment_score") is not None else 0.0))
    result.setdefault("rating", float(rating_val) if rating_val is not None else 0.0)

    # recommendation derived from rating if available, otherwise from decision
    rec = rating_to_recommendation(rating_val if rating_val is not None else None, decision)
    result.setdefault("recommendation", rec)

    # gpt_judgment: short textual summary combining decision, rating and news hints
    try:
        parts = [f"Decision={decision}"]
        if rating_val is not None:
            parts.append(f"rating={float(rating_val):.2f}")
        parts.append(f"recommendation={rec}")
        nc = result.get("news_count", 0)
        parts.append(f"news_count={nc}")
        ss = result.get("sentiment_score", 0.0)
        parts.append(f"sentiment={float(ss):.3f}")
        result.setdefault("gpt_judgment", "; ".join(parts))
    except Exception:
        pass

    # 書き込み
    os.makedirs(os.path.dirname(OUTPUT_PATH) or '.', exist_ok=True)
    with open(OUTPUT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")

    print(f"✅ IFD generated for {symbol}: TP={tp}, SL={sl}")
    return result


if __name__ == "__main__":
    # DryRun用：全銘柄をテスト生成
    test_prices = {
        "JP225": 51200,
        "NQ100": 17900,
        "XAUUSD": 2375.5,
        "XAGUSD": 28.42,
        "NGAS": 3.02,
        "GER40": 18450,
    }

    print("🚀 Running DryRun for all symbols...\n")
    for sym, price in test_prices.items():
        try:
            generate_ifd(sym, price, "STRONG_GO")
        except Exception as e:
            print(f"⚠️ {sym}: {e}")
    print("\n✅ Done — check output/ifd_orders.jsonl")
