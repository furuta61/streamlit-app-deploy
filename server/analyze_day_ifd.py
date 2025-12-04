# -*- coding: utf-8 -*-
"""
CFD3 AI Trade System Ver.200
ハイブリッドIFD（GMOスクショ × 30m/4H × ニュース × Dawn形式）
"""

import pandas as pd, numpy as np, os, json, random
from pathlib import Path
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

# =====================================
# 依存関数
# =====================================
import sys
sys.path.append(str(BASE_DIR.parent))

from server.analyze_swing_multi_core import (
    analyze_news_sentiment,
    calc_tech
)

def clean_dataframe(df, symbol=None):
    """異常値フィルタ（簡易版）"""
    if "close" in df.columns:
        df = df[df["close"] > 0]
    return df


# ====================================================================
# AI判定（30m + 4H + ニュース + GMO価格 すべて統合）
# ====================================================================
def ai_hybrid_decision(symbol, t30, t240, news, gmo_price):
    prompt = f"""
銘柄: {symbol}

■30分足
終値 {t30['close']:.2f}
RSI {t30['rsi']:.1f}
SMA25 {t30['sma25']:.1f}
SMA75 {t30['sma75']:.1f}
MACD {t30['macd']:.3f}
Signal {t30['signal']:.3f}

■4時間足
終値 {t240['close']:.2f}
SMA25 {t240['sma25']:.1f}
SMA75 {t240['sma75']:.1f}

■ニュース感情
ポジ {news['positive']}%
中立 {news['neutral']}%
ネガ {news['negative']}%
要約: {news['summary']}

■GMO現在値
現在価格: {gmo_price}

次の形式で1つだけ返してください：

{{
 "direction": "buy/sell/stop",
 "comment": "理由を簡潔に",
 "confidence": 数値 (0-100)
}}
"""
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0.25,
        )
        import re
        raw = res.choices[0].message.content

        if "```" in raw:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                raw = m.group(0)

        data = json.loads(raw)

        if not isinstance(data, dict):
            raise ValueError("invalid json")

        for k in ["direction", "confidence", "comment"]:
            if k not in data:
                data[k] = "stop" if k=="direction" else (50 if k=="confidence" else "補完")

        return data

    except Exception as e:
        print(f"[AI ERROR] fallback: {e}")
        return {
            "direction": "stop",
            "confidence": 50,
            "comment": f"AI解析失敗 ({e})"
        }


# ====================================================================
# IFD作成（entry=GMO現在値、SL/TPはATRで計算）
# ====================================================================
def build_ifd(direction, price, atr):
    if direction == "buy":
        tp1 = price * 1.004
        tp2 = price * 1.008
        sl  = price - atr
    elif direction == "sell":
        tp1 = price * 0.996
        tp2 = price * 0.992
        sl  = price + atr
    else:
        return price, price, price, price
    return price, sl, tp1, tp2


# ====================================================================
# メイン：ハイブリッドIFD
# ====================================================================
def analyze_day_ifd(symbols=["日本225","米国NQ100ミニ","ドイツ40","金スポット"], gmo_price=None):
    """
    ハイブリッドIFD分析
    
    Args:
        symbols: 分析対象銘柄リスト
        gmo_price: GMO現在値（Noneの場合はCSVから取得）
    """
    results = []

    for sym in symbols:
        try:
            # -------------------------
            # 30分足 / 4H データ読み込み
            # -------------------------
            code_map = {
                "日本225":"JP225",
                "米国NQ100ミニ":"NAS100",
                "ドイツ40":"GER40",
                "金スポット":"XAUUSD"
            }
            code = code_map.get(sym, sym)

            f30  = BASE_DIR / "data" / f"FOREXCOM_{code}_30.csv"
            f240 = BASE_DIR / "data" / f"FOREXCOM_{code}_240.csv"

            if not f30.exists() or not f240.exists():
                results.append({"symbol": sym, "markdown": f"⚠️ {sym} CSV未検出"})
                continue

            df30  = clean_dataframe(pd.read_csv(f30), sym)
            df240 = clean_dataframe(pd.read_csv(f240), sym)

            t30  = calc_tech(df30)
            t240 = calc_tech(df240)

            # GMO価格がない場合はCSVの終値を使用
            if gmo_price is None:
                gmo_price = t30['close']

            # -------------------------
            # ニュース感情
            # -------------------------
            news = analyze_news_sentiment(sym)

            # -------------------------
            # AI統合判定
            # -------------------------
            ai = ai_hybrid_decision(sym, t30, t240, news, gmo_price)

            # -------------------------
            # IFD計算（entry=GMO現在値）
            # -------------------------
            entry, sl, tp1, tp2 = build_ifd(ai["direction"], gmo_price, (t30["atr"]+t240["atr"])/2)

            # -------------------------
            # 推奨度（星）
            # -------------------------
            stars = (
                "★★★★★" if ai["confidence"]>=85 else
                "★★★★☆" if ai["confidence"]>=70 else
                "★★★☆☆" if ai["confidence"]>=55 else
                "★★☆☆☆"
            )

            # -------------------------
            # Dawn形式
            # -------------------------
            markdown = f"""
| trade_mode | 銘柄 | 方向 | entry_price | SL | TP1 | TP2 | 判定 | 推奨度 | コメント |
|------------|------|------|-------------|------|------|------|--------|----------|-----------|
| HYBRID | {sym} | {ai['direction']} | {entry:.1f} | {sl:.1f} | {tp1:.1f} | {tp2:.1f} | {ai['direction'].upper()} | {stars} | {ai['comment']} |

### 📰 ニュース感情
🟢{news['positive']}% ⚪️{news['neutral']}% 🔴{news['negative']}%
リスク: {news['risk_score']}
要約: {news['summary']}
"""
            results.append({"symbol": sym, "markdown": markdown})

        except Exception as e:
            import traceback
            print(f"[ERROR] {sym}: {traceback.format_exc()}")
            results.append({"symbol": sym, "markdown": f"⚠️ {sym} 解析失敗: {e}"})

    return {"status": "ok", "count": len(results), "results": results}
