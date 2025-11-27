import pandas as pd, numpy as np, random, time, os
from pathlib import Path
from openai import OpenAI

# 環境変数からAPIキーを取得
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY)

# パス設定
BASE_DIR = Path(__file__).resolve().parent

def analyze_news_sentiment(symbol):
    """ダミーニュース感情分析"""
    return {
        "summary": f"{symbol}の市場動向は中立的",
        "positive": 40,
        "neutral": 40,
        "negative": 20
    }

def get_win_rate(symbol):
    """ダミー勝率（実際はバックテスト結果から取得）"""
    return 0.65  # 65%の勝率

def calc_tech_indicators(df):
    close = df["close"].astype(float)
    sma25 = close.rolling(25).mean()
    sma75 = close.rolling(75).mean()
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    atr = close.diff().abs().rolling(14).mean().iloc[-1]
    rsi = 100 - (100 / (1 + (close.diff().clip(lower=0).rolling(14).mean() /
                             close.diff().clip(upper=0).abs().rolling(14).mean())))
    return {
        "close": close.iloc[-1],
        "sma25": sma25.iloc[-1],
        "sma75": sma75.iloc[-1],
        "macd": macd.iloc[-1],
        "signal": signal.iloc[-1],
        "rsi": rsi.iloc[-1],
        "atr": atr,
    }

def ai_direction_analysis(symbol, tech, news):
    prompt = f"""
あなたはプロトレーダーAIです。次のデータをもとに「買い/売り」を推定してください。

銘柄: {symbol}
終値: {tech['close']}
SMA25: {tech['sma25']} / SMA75: {tech['sma75']}
MACD: {tech['macd']} / Signal: {tech['signal']}
RSI: {tech['rsi']}
ATR: {tech['atr']}
ニュース感情: {news['summary']} (ポジ: {news['positive']}%, ネガ: {news['negative']}%)

以下の3つをJSONで返してください：
{{
 "direction": "buy or sell",
 "confidence": 0〜100,
 "comment": "簡潔な理由"
}}
"""
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0.3,
        )
        text = res.choices[0].message.content
        import json
        return json.loads(text)
    except Exception as e:
        return {"direction":"buy","confidence":60,"comment":f"AI解析失敗: {e}"}

def analyze_swing_multi_core(symbols):
    results = []
    for sym in symbols:
        try:
            # CSVパスを調整（server/からの相対パスまたは絶対パス）
            csv_path = BASE_DIR / "data" / f"FOREXCOM_{sym}_240.csv"
            if not csv_path.exists():
                csv_path = BASE_DIR.parent / "data" / f"FOREXCOM_{sym}_240.csv"
            
            df = pd.read_csv(csv_path)
            tech = calc_tech_indicators(df)
            news = analyze_news_sentiment(sym)
            ai_eval = ai_direction_analysis(sym, tech, news)
            win_rate = get_win_rate(sym)

            entry = tech["close"]
            atr = tech["atr"]
            direction = ai_eval["direction"]
            tp1 = entry * (1.003 if direction == "buy" else 0.997)
            tp2 = entry * (1.006 if direction == "buy" else 0.994)
            sl = entry - atr if direction == "buy" else entry + atr
            conf = ai_eval["confidence"] * (0.8 + win_rate * 0.2)
            conf = min(100, round(conf, 1))

            md = f"""
| trade_mode | 銘柄 | 方向 | entry_price | SL | TP1 | TP2 | order_type | 判定 | ニュースロック | 推奨度 | ロット | CUT条件 |
|-------------|------|------|--------------|------|------|------|------------|--------|----------------|----------|--------|------------|
| DAY6H | {sym} | {'買い' if direction=='buy' else '売り'} | {entry:.1f} | {sl:.1f} | {tp1:.1f} | {tp2:.1f} | 指値 | {'STRONG_GO' if conf>85 else 'GO'} | false | {'★★★★★' if conf>80 else '★★☆☆☆'} | 6 | SMA25 < SMA75 or MACD < Signal |

### 🧠 AIコメント
- {ai_eval['comment']}
### 📰 ニュース分析
- 感情: 🟢{news['positive']}% ⚪️{news['neutral']}% 🔴{news['negative']}%
- 概要: {news['summary']}
"""
            results.append({
                "symbol": sym,
                "entry": entry,
                "confidence": conf,
                "markdown": md
            })
        except Exception as e:
            results.append({
                "symbol": sym,
                "error": str(e),
                "markdown": f"⚠️ {sym} の分析に失敗: {e}"
            })
    return results
