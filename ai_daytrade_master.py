# -*- coding: utf-8 -*-
"""
AI DayTrade Master (IFDOCO生成対応)
30分足＋4時間足＋スクショ（Vision）＋ニュースを統合判断する
"""

from __future__ import annotations
import pandas as pd, numpy as np, json, logging, random, os
from pathlib import Path
from openai import OpenAI
from datetime import datetime
try:
    from server.news_fetcher import fetch_latest_rss
except ImportError:
    def fetch_latest_rss(limit=6):
        return []

logger = logging.getLogger("daytrade_ai")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

BASE_DIR = Path(__file__).resolve().parent


def fetch_latest_rss(limit=6):
    """ニュース取得のフォールバック実装"""
    try:
        from server.news_fetcher import fetch_latest_rss as fetch_rss
        return fetch_rss(limit=limit)
    except Exception:
        return [{"title": "ニュース取得なし", "summary": ""}]


def calc_indicators(df: pd.DataFrame):
    close = df["close"].astype(float)
    sma25 = close.rolling(25).mean()
    sma75 = close.rolling(75).mean()
    macd = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    signal = macd.ewm(span=9).mean()
    rsi = 100 - (100 / (1 + (close.diff().clip(lower=0).rolling(14).mean() /
                             close.diff().clip(upper=0).abs().rolling(14).mean())))
    atr = close.diff().abs().rolling(14).mean().iloc[-1]
    return dict(close=close.iloc[-1], sma25=sma25.iloc[-1],
                sma75=sma75.iloc[-1], macd=macd.iloc[-1],
                signal=signal.iloc[-1], rsi=rsi.iloc[-1], atr=atr)


def adaptive_weight(df: pd.DataFrame):
    """過去30足のバックテストから最適重みを算出"""
    try:
        close = df["close"].astype(float)
        sma25 = close.rolling(25).mean()
        sma75 = close.rolling(75).mean()
        macd = close.ewm(span=12).mean() - close.ewm(span=26).mean()
        signal = macd.ewm(span=9).mean()
        rsi = 100 - (100 / (1 + (close.diff().clip(lower=0).rolling(14).mean() /
                                 close.diff().clip(upper=0).abs().rolling(14).mean())))
        
        df = df.copy()
        df["rsi"] = rsi
        df["macd"] = macd
        df["signal"] = signal
        df["rsi_sig"] = np.where(df["rsi"] > 70, -1, np.where(df["rsi"] < 30, 1, 0))
        df["macd_sig"] = np.where(df["macd"] > df["signal"], 1, -1)
        score = (df["rsi_sig"] + df["macd_sig"]).tail(30).mean()
        tech_weight = min(max(0.5 + score * 0.1, 0.2), 0.8)  # 技術重み (0.2〜0.8)
        news_weight = 1 - tech_weight
        return tech_weight, news_weight
    except Exception:
        return 0.6, 0.4


def analyze_daytrade(symbols: list[str]):
    results = []
    news_items = fetch_latest_rss(limit=6)
    news_text = " ".join([n["title"] for n in news_items])[:600]

    for sym in symbols:
        try:
            csv_30 = BASE_DIR / "data" / f"FOREXCOM_{sym}_30.csv"
            csv_240 = BASE_DIR / "data" / f"FOREXCOM_{sym}_240.csv"
            
            if not csv_30.exists() or not csv_240.exists():
                logger.warning(f"[DayTradeAI] CSV not found for {sym}")
                results.append({
                    "symbol": sym,
                    "error": "CSV not found",
                    "markdown": f"⚠️ {sym} のCSVファイルが見つかりません"
                })
                continue
            
            df30 = pd.read_csv(csv_30)
            df240 = pd.read_csv(csv_240)

            tech30 = calc_indicators(df30)
            tech240 = calc_indicators(df240)
            tech_w, news_w = adaptive_weight(df30)

            prompt = f"""
あなたは高精度デイトレAIです。
銘柄: {sym}
--- テクニカル分析 ---
30分足: RSI={tech30['rsi']:.2f}, MACD={tech30['macd']:.3f}, SMA25={tech30['sma25']:.1f}, SMA75={tech30['sma75']:.1f}
4時間足: RSI={tech240['rsi']:.2f}, MACD={tech240['macd']:.3f}, SMA25={tech240['sma25']:.1f}, SMA75={tech240['sma75']:.1f}
ATR={tech30['atr']:.2f}
--- ニュース概要 ---
{news_text}
--- 重み ---
テクニカル={tech_w:.2f}, ニュース={news_w:.2f}

出力形式（JSONのみ）:
{{
 "direction": "buy or sell or stop",
 "entry_price": {tech30['close']:.1f},
 "tp": 数値,
 "sl": 数値,
 "confidence": 0〜100,
 "reason": "日本語で簡潔に理由を述べる"
}}
"""

            res = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                timeout=30
            )
            text = res.choices[0].message.content.strip()
            if "```" in text:
                import re
                m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
                if m:
                    text = m.group(1)
            data = json.loads(text)

            conf = round(data["confidence"] * (tech_w * 0.7 + news_w * 0.3), 1)
            entry = data["entry_price"]

            md = f"""
| trade_mode | 銘柄 | 方向 | entry | SL | TP | 信頼度 | CUT条件 |
|-------------|------|------|--------|------|------|----------|------------|
| DAYTRADE | {sym} | {'買い' if data['direction']=='buy' else '売り' if data['direction']=='sell' else '停止'} | {entry:.1f} | {data['sl']:.1f} | {data['tp']:.1f} | {conf}% | SMA25 < SMA75 or MACD < Signal |

### 💬 AIコメント
- {data['reason']}

### 📊 アダプティブ重み
- テクニカル重視度: {tech_w:.1%}
- ニュース重視度: {news_w:.1%}
"""
            results.append(dict(symbol=sym, entry=entry, confidence=conf, markdown=md))

        except Exception as e:
            logger.exception(f"[AdaptiveAI] {sym} error: {e}")
            results.append({
                "symbol": sym,
                "error": str(e),
                "markdown": f"⚠️ {sym} の分析に失敗: {e}"
            })

    return {"status": "ok", "count": len(results), "results": results}
