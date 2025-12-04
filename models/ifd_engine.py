# -*- coding: utf-8 -*-
"""
IFD Engine - GMOハイブリッドIFD計算エンジン
既存のanalyze_unified_ifd.pyのロジックを統合・改善
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import joblib
from pathlib import Path

# モデルパス
BASE_DIR = Path(__file__).resolve().parent.parent
DIRECTION_MODEL_PATH = BASE_DIR / "direction_model.pkl"
TP_SL_MODEL_PATH = BASE_DIR / "tp_sl_model.pkl"

# GMO現在値（手動更新）
GMO_PRICES = {
    "JP225": {"bid": 49550.6, "ask": 49553.6},
    "NAS100": {"bid": 25623.0, "ask": 25623.7},
    "GER40": {"bid": 23757.5, "ask": 23760.5},
    "XAUUSD": {"bid": 4214.78, "ask": 4214.93},
}

# ティック幅
TICK_SIZES = {
    "JP225": 5.0,
    "NAS100": 0.5,
    "GER40": 0.5,
    "XAUUSD": 0.05,
}

# モデルロード
def load_models():
    """AIモデルを読み込む"""
    try:
        direction_model = joblib.load(DIRECTION_MODEL_PATH)
    except:
        direction_model = None
    
    try:
        tp_sl_model = joblib.load(TP_SL_MODEL_PATH)
    except:
        tp_sl_model = None
    
    return direction_model, tp_sl_model

direction_model, tp_sl_model = load_models()


def calculate_technicals(df: pd.DataFrame) -> Dict:
    """
    テクニカル指標を計算
    
    Args:
        df: OHLC データフレーム (time, open, high, low, close, volume)
    
    Returns:
        テクニカル指標の辞書
    """
    close = df["close"].astype(float)
    
    # 移動平均
    sma25 = close.rolling(25).mean().iloc[-1]
    sma75 = close.rolling(75).mean().iloc[-1]
    
    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    macd = macd_line.iloc[-1]
    signal = macd_line.ewm(span=9).mean().iloc[-1]
    
    # ATR
    atr = close.diff().abs().rolling(14).mean().iloc[-1]
    
    # RSI
    diff = close.diff()
    gains = diff.clip(lower=0)
    losses = (-diff.clip(upper=0)).abs()
    avg_gain = gains.rolling(14).mean()
    avg_loss = losses.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = (100 - 100 / (1 + rs)).iloc[-1]
    rsi = float(np.clip(rsi, 0, 100))
    
    return {
        "close": close.iloc[-1],
        "sma25": sma25,
        "sma75": sma75,
        "macd": macd,
        "signal": signal,
        "atr": atr,
        "rsi": rsi,
    }


def calculate_ai_score(tech: Dict, sentiment: Dict) -> float:
    """
    AIスコアを計算（方向性予測）
    
    Args:
        tech: テクニカル指標
        sentiment: ニュース感情分析結果
    
    Returns:
        0-1のスコア（0.65以上でGO）
    """
    if direction_model is None:
        return 0.5  # フォールバック
    
    features = [
        tech.get("rsi", 50),
        tech.get("sma25", 0),
        tech.get("sma75", 0),
        tech.get("macd", 0),
        tech.get("signal", 0),
        sentiment.get("positive", 0) / 100,
        sentiment.get("negative", 0) / 100,
    ]
    
    X = pd.DataFrame([features], columns=[
        "RSI", "SMA25", "SMA75", "MACD", "Signal",
        "sentiment_pos", "sentiment_neg"
    ])
    
    try:
        proba = direction_model.predict_proba(X)[0]
        return float(proba[1])  # 上昇確率
    except:
        return 0.5


def mid_price(prices: Dict) -> float:
    """BID/ASKからミッド価格を算出"""
    return (prices["bid"] + prices["ask"]) / 2


def round_to_tick(price: float, tick: float) -> float:
    """ティック単位に丸める"""
    return round(price / tick) * tick


def build_ifd_from_gmo(
    symbol: str,
    tech: Dict,
    sentiment: Dict,
    ai_score: float,
    gmo_mid: float
) -> Dict:
    """
    GMO現在値ベースでIFDを計算
    
    Args:
        symbol: 銘柄コード (JP225, NAS100, GER40, XAUUSD)
        tech: テクニカル指標
        sentiment: ニュース感情
        ai_score: AIスコア (0-1)
        gmo_mid: GMOミッド価格
    
    Returns:
        IFD情報の辞書
    """
    tick = TICK_SIZES.get(symbol, 1.0)
    
    # 方向判定
    if ai_score >= 0.65:
        direction = "buy" if tech["macd"] > tech["signal"] else "sell"
        ai_judge = "GO"
    elif ai_score >= 0.50:
        direction = "stay"
        ai_judge = "HOLD"
    else:
        direction = "stay"
        ai_judge = "NG"
    
    # STAY の場合
    if direction == "stay":
        entry = round_to_tick(gmo_mid, tick)
        return {
            "direction": "stay",
            "entry": entry,
            "sl": entry,
            "tp1": entry,
            "tp2": entry,
            "order_type": "指値",
            "judge": "HOLD",
            "stars": "★☆☆☆☆",
            "ai_score": ai_score,
            "ai_judge": ai_judge,
        }
    
    # ATR取得（フォールバック付き）
    atr = tech.get("atr", 0)
    if atr is None or atr <= 0:
        atr = max(abs(tech["close"]) * 0.001, 100)
    
    # リスク係数
    risk_k = 1.5
    tp1_k = 1.5
    tp2_k = 3.0
    
    entry = round_to_tick(gmo_mid, tick)
    
    if direction == "buy":
        sl = round_to_tick(entry - risk_k * atr, tick)
        tp1 = round_to_tick(entry + tp1_k * atr, tick)
        tp2 = round_to_tick(entry + tp2_k * atr, tick)
    else:  # sell
        sl = round_to_tick(entry + risk_k * atr, tick)
        tp1 = round_to_tick(entry - tp1_k * atr, tick)
        tp2 = round_to_tick(entry - tp2_k * atr, tick)
    
    stars = "★★★★★" if ai_score >= 0.7 else "★★★★☆" if ai_score >= 0.65 else "★★★☆☆"
    
    return {
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "order_type": "指値",
        "judge": "GO",
        "stars": stars,
        "ai_score": ai_score,
        "ai_judge": ai_judge,
    }


def analyze_entry(
    symbol: str,
    df: pd.DataFrame,
    timeframe: str = "30m",
    sentiment: Optional[Dict] = None
) -> Dict:
    """
    エントリー判定のメイン関数
    
    Args:
        symbol: 銘柄コード
        df: OHLC DataFrame
        timeframe: 時間足 (30m, 4h など)
        sentiment: ニュース感情分析結果（オプション）
    
    Returns:
        IFD判定結果
    """
    # デフォルト感情
    if sentiment is None:
        sentiment = {"positive": 50, "neutral": 30, "negative": 20}
    
    # テクニカル計算
    tech = calculate_technicals(df)
    
    # AIスコア
    ai_score = calculate_ai_score(tech, sentiment)
    
    # GMO価格取得
    if symbol not in GMO_PRICES:
        return {"error": f"Symbol {symbol} not supported"}
    
    gmo_mid = mid_price(GMO_PRICES[symbol])
    
    # IFD計算
    ifd = build_ifd_from_gmo(symbol, tech, sentiment, ai_score, gmo_mid)
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "decision": ifd["judge"],
        "direction": ifd["direction"],
        "entry_price": round(ifd["entry"], 2),
        "take_profit_1": round(ifd["tp1"], 2),
        "take_profit_2": round(ifd["tp2"], 2),
        "stop_loss": round(ifd["sl"], 2),
        "order_type": ifd["order_type"],
        "stars": ifd["stars"],
        "ai_score": round(ifd["ai_score"], 3),
        "ai_judge": ifd["ai_judge"],
        "technicals": {
            "rsi": round(tech["rsi"], 1),
            "sma25": round(tech["sma25"], 2),
            "sma75": round(tech["sma75"], 2),
            "macd": round(tech["macd"], 2),
            "signal": round(tech["signal"], 2),
            "atr": round(tech["atr"], 2) if tech["atr"] else None,
        },
        "sentiment": sentiment,
    }
