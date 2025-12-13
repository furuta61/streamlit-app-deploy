from __future__ import annotations
from typing import Dict, Any, Tuple

# 重み（必要に応じて調整）
TECH_WEIGHT = 1.0
NEWS_WEIGHT = 0.5

# 銘柄別デフォルト（ATRが無い時の%フォールバック）
POINTS = {
    "JP225": {"tp": 0.023, "sl": 0.010, "round": 0},
    "NQ100": {"tp": 0.020, "sl": 0.010, "round": 0},
    "XAUUSD": {"tp": 0.015, "sl": 0.008, "round": 2},
    "XAGUSD": {"tp": 0.025, "sl": 0.012, "round": 2},
    "NGAS":  {"tp": 0.030, "sl": 0.015, "round": 3},
    "GER40": {"tp": 0.018, "sl": 0.009, "round": 0},
}

def _round_by(v: float, digits: int) -> float:
    return float(round(v, digits))

def _adjust_rating_with_screener(rating: float, screener: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    adj = 0.0
    rsi = screener.get("RSI")
    recommend = str(screener.get("Recommend") or "NEUTRAL").upper()
    # RSI
    if rsi is not None:
        if rsi >= 70: adj -= 0.5
        elif rsi <= 30: adj += 0.5
    # TV Recommend
    if "STRONG_BUY" in recommend: adj += 0.7
    elif recommend == "BUY": adj += 0.3
    elif "STRONG_SELL" in recommend: adj -= 0.7
    elif "SELL" in recommend: adj -= 0.3
    return rating + adj, {"rating_adjustment": adj}

def calculate_advanced_tech_score(screener: Dict[str, Any]) -> float:
    """
    複合的テクニカルスコア（-6〜+6目安）
    SMA差(%)、RSI帯、MACD/Signalの位置関係、TVの推奨を加点/減点
    """
    score = 0.0
    sma25 = screener.get("SMA25")
    sma75 = screener.get("SMA75")
    if sma25 and sma75:
        diff_pct = ((sma25 - sma75) / sma75) * 100
        if diff_pct > 2.0: score += 2.5
        elif diff_pct > 0.5: score += 1.5
        elif diff_pct < -2.0: score -= 2.5
        elif diff_pct < -0.5: score -= 1.5

    rsi = screener.get("RSI")
    if rsi is not None:
        if 20 <= rsi < 30: score += 2.0
        elif 30 <= rsi <= 40: score += 1.5
        elif 60 <= rsi <= 70: score -= 1.5
        elif 70 < rsi <= 80: score -= 2.0

    macd = screener.get("MACD")
    macd_signal = screener.get("MACD_signal")
    if macd is not None and macd_signal is not None:
        if macd > macd_signal and macd > 0: score += 1.5
        elif macd > macd_signal and macd <= 0: score += 1.0
        elif macd < macd_signal and macd < 0: score -= 1.5
        elif macd < macd_signal and macd >= 0: score -= 1.0

    recommend = str(screener.get("Recommend", "")).upper()
    if "STRONG_BUY" in recommend: score += 1.0
    elif "BUY" in recommend: score += 0.5
    elif "STRONG_SELL" in recommend: score -= 1.0
    elif "SELL" in recommend: score -= 0.5

    return score

def analyze_signal(payload: Dict[str, Any],
                   news_score: float | None,
                   tech_score: float | None,
                   screener: Dict[str, Any] | None) -> Dict[str, Any]:
    # screener があれば高度化スコアで上書き
    if screener is not None:
        tech_score = calculate_advanced_tech_score(screener)

    base_rating = (TECH_WEIGHT * (tech_score or 0)) + (NEWS_WEIGHT * (news_score or 0))
    meta: Dict[str, Any] = {"tech_score": tech_score, "news_score": news_score}

    # ニュース項目による補正
    try:
        news_items = payload.get("news_items", []) if isinstance(payload, dict) else []
        news_count = len(news_items)
    except Exception:
        news_items = []
        news_count = 0
    meta["news_count"] = news_count

    # ニュース数に基づく加点: 5件以上で +0.3、10件以上で +0.5
    news_adj = 0.0
    if news_count >= 10:
        news_adj = 0.5
    elif news_count >= 5:
        news_adj = 0.3
    meta["news_score"] = news_adj

    # センチメントによる補正（payload に sentiment_score があれば ±0.2 のスケールで反映）
    try:
        sentiment_score = float(payload.get("sentiment_score", 0.0) or 0.0)
    except Exception:
        sentiment_score = 0.0
    meta["sentiment_score"] = sentiment_score
    sentiment_adj = max(min(sentiment_score, 1.0), -1.0) * 0.2

    rating = base_rating + news_adj + sentiment_adj

    if screener:
        new_rating, extra = _adjust_rating_with_screener(rating, screener)
        meta.update(extra)
        rating = new_rating

    # 最終評価値を meta に保存
    meta["final_rating"] = rating

    return {"rating": rating, "meta": meta}

def generate_ifd(symbol: str, entry_price: float, decision_label: str, rating: float, meta: Dict[str, Any]) -> Dict[str, Any]:
    """ ATRがあれば動的TP/SL、無ければ%フォールバック """
    p = POINTS.get(symbol, {"tp": 0.02, "sl": 0.01, "round": 0})
    atr = meta.get("screener", {}).get("ATR") if meta.get("screener") else None

    if atr and atr > 0:
        tp = _round_by(entry_price + (atr * 2.0), p["round"])
        sl = _round_by(entry_price - (atr * 1.5), p["round"])
        atr_used = True
    else:
        tp = _round_by(entry_price * (1 + p["tp"]), p["round"])
        sl = _round_by(entry_price * (1 - p["sl"]), p["round"])
        atr_used = False

    return {
        "symbol": symbol,
        "decision": decision_label,
        "entry_price": float(entry_price),
        "take_profit": tp,
        "stop_loss": sl,
        "rating": float(rating),
        "atr_used": atr_used,
        # For safety: mark generated IFDs as manual-only by default. Downstream
        # execution components should check this flag and require human action.
        "auto_execute": False,
        "trusted_csv": False,
        **meta,
    }
