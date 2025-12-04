# -*- coding: utf-8 -*-
"""
analyze_unified_ifd.py
AIニュース統合版 — ニュース × テクニカル × IFD自動生成

CFD3 DawnAI Core Engine
- GPT-4o-mini ニュース解析
- テクニカル指標（SMA, MACD, RSI, ATR）
- 投票システムベース IFD生成
"""

import os
import json
import numpy as np
import pandas as pd
from openai import OpenAI

# --- OpenAI API 初期化 ---
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

# --- 基本設定 ---
POINT_VALUE_JPY = {
    "JP225": 100,
    "NAS100": 20,
    "GER40": 25,
    "XAUUSD": 100
}


# ====================================================
# 🧩 1. AIニュース解析モジュール
# ====================================================

def analyze_news_ai(symbol, text):
    """
    AIでニュース本文を解析し、要約・方向性・影響度を推定
    
    出力:
    {
      "summary": "短い日本語要約",
      "direction": "buy/sell/neutral",
      "impact_score": 0-100,
      "duration": "短期/中期/長期",
      "keywords": ["キーワード1", "キーワード2", ...]
    }
    """
    if not text or len(text.strip()) == 0:
        return {
            "summary": "",
            "direction": "neutral",
            "impact_score": 50,
            "duration": "中期",
            "keywords": []
        }

    prompt = f"""
あなたはプロの金融アナリストです。
以下のニュース本文から、{symbol} の市場への影響を評価してください。
出力は **必ず** 次のJSON形式で返してください：

{{
  "summary": "<短い日本語要約（30字以内）>",
  "direction": "<buy/sell/neutral>",
  "impact_score": <0-100の数値>,
  "duration": "<短期/中期/長期>",
  "keywords": ["関連キーワード1","関連キーワード2","関連キーワード3"]
}}

ニュース本文:
{text}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200
        )
        content = response.choices[0].message.content.strip()
        return json.loads(content)
    except Exception as e:
        print(f"[WARN] AIニュース解析に失敗: {e}")
        return {
            "summary": text[:30] if text else "",
            "direction": "neutral",
            "impact_score": 50,
            "duration": "中期",
            "keywords": []
        }


# ====================================================
# 🧩 2. 補助関数群
# ====================================================

def short_comment(text):
    """テキスト短縮（25字以内）"""
    return text[:25] + "..." if len(text) > 25 else text


def detect_regime(t30, t240):
    """
    レジーム判定：range / up / down
    
    - range: SMA25 ≈ SMA75（0.03%以内）
    - up: 4H SMA25 > SMA75
    - down: それ以外
    """
    if abs(t30.get("sma25", 0) - t30.get("sma75", 0)) < 0.0003 * max(t30.get("sma25", 1), 1):
        return "range"
    
    if t240.get("sma25", 0) > t240.get("sma75", 0):
        return "up"
    
    return "down"


def calc_rr(entry, sl, tp, side):
    """
    Risk/Reward 比率を計算
    
    RR = Reward / Risk
    """
    if side == "buy":
        risk = max(entry - sl, 1e-9)
        reward = max(tp - entry, 0.0)
    elif side == "sell":
        risk = max(sl - entry, 1e-9)
        reward = max(entry - tp, 0.0)
    else:
        return 0.0
    
    return reward / risk if risk > 0 else 0.0


def build_ifd(direction, price, atr):
    """
    IFD（逆指値付き注文）を構築
    
    direction: "buy" or "sell"
    price: Entry価格
    atr: Average True Range
    
    戻り値: (entry, sl, tp1, tp2)
    """
    if direction == "buy":
        entry = price
        sl = price - atr
        tp1 = price + 2 * atr
        tp2 = price + 3 * atr
    elif direction == "sell":
        entry = price
        sl = price + atr
        tp1 = price - 2 * atr
        tp2 = price - 3 * atr
    else:
        entry = sl = tp1 = tp2 = price
    
    return entry, sl, tp1, tp2


def build_cut(t30, t240):
    """
    カット条件（損切判定ロジック）を構築
    """
    s1 = f"SMA25<{t240.get('sma75', 0):.2f}" if t240.get('sma25', 0) < t240.get('sma75', 0) else f"SMA25>{t240.get('sma75', 0):.2f}"
    s2 = "MACD<Signal" if t30.get('macd', 0) < t30.get('signal', 0) else "MACD>Signal"
    return f"{s1} or {s2}"


# ====================================================
# 🧩 3. メイン分析ロジック
# ====================================================

def analyze_symbol(code, price, t30, t240, news_text):
    """
    単一銘柄の IFD 生成
    
    入力:
      code: 銘柄コード（JP225など）
      price: 現在価格
      t30: 30分足テクニカル指標
      t240: 4時間足テクニカル指標
      news_text: 最新ニュース本文
    
    出力:
      dict形式のIFD結果
    """
    
    # ATR計算（30分と4時間の平均）
    atr = (t30.get("atr", 0) + t240.get("atr", 0)) / 2
    if atr == 0 or np.isnan(atr):
        atr = price * 0.01
    
    # レジーム判定
    regime = detect_regime(t30, t240)
    
    # --- AIニュース分析 ---
    news = analyze_news_ai(code, news_text)
    news_direction = news.get("direction", "neutral")
    
    # --- 投票システム（テクニカル + ニュース） ---
    votes = {"buy": 0, "sell": 0}
    
    # SMA25 > SMA75（4H）
    if t240.get("sma25", 0) > t240.get("sma75", 0):
        votes["buy"] += 1
    else:
        votes["sell"] += 1
    
    # MACD > Signal（30M）
    if t30.get("macd", 0) > t30.get("signal", 0):
        votes["buy"] += 1
    else:
        votes["sell"] += 1
    
    # ニュース方向性
    if news_direction == "buy":
        votes["buy"] += 1
    elif news_direction == "sell":
        votes["sell"] += 1
    
    # RSI（30M）
    rsi_30 = t30.get("rsi", 50)
    if rsi_30 > 55:
        votes["buy"] += 1
    elif rsi_30 < 45:
        votes["sell"] += 1
    
    # --- 方向決定 ---
    final_direction = "buy" if votes["buy"] > votes["sell"] else "sell"
    
    # --- RR計算 ---
    rr = calc_rr(price, price - atr, price + 2 * atr, final_direction)
    
    # --- 判定 ---
    if rr > 1.5 and votes[final_direction] >= 3:
        decision = "STRONG_GO"
        stars = "★★★★★"
        lots = 6
    elif rr > 1.2 and votes[final_direction] >= 2:
        decision = "GO"
        stars = "★★★★☆"
        lots = 3
    else:
        decision = "WAIT"
        stars = "★★★☆☆"
        lots = 0
    
    # --- IFD構築 ---
    entry, sl, tp1, tp2 = build_ifd(final_direction, price, atr)
    cut = build_cut(t30, t240)
    comment = short_comment(news.get("summary", ""))
    
    return {
        "trade_mode": "DAY6H",
        "symbol": code,
        "direction": final_direction.upper(),
        "entry_price": round(entry, 2),
        "sl": round(sl, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "order_type": "指値",
        "判定": decision,
        "news_direction": news_direction,
        "impact_score": news.get("impact_score", 50),
        "duration": news.get("duration", "中期"),
        "keywords": ",".join(news.get("keywords", [])),
        "stars": stars,
        "lots": lots,
        "cut": cut,
        "comment": comment,
        "rr": round(rr, 2),
        "regime": regime,
        "votes_buy": votes["buy"],
        "votes_sell": votes["sell"]
    }


# ====================================================
# 🧩 4. メイン処理（複数銘柄分析）
# ====================================================

def analyze_unified_ifd(gmo_prices=None, tech_map=None, news_map=None, mode="DAY6H"):
    """
    複数銘柄の統合IFD分析
    
    入力:
      gmo_prices: {"日本225": price, ...}
      tech_map: {"JP225": (t30, t240, t1D), ...}
      news_map: {"日本225": "ニュース本文", ...}
      mode: "DAY6H" (デフォルト)
    
    出力:
      pandas DataFrame + HTML テーブル
    """
    
    # デフォルト値
    if gmo_prices is None:
        gmo_prices = {}
    if tech_map is None:
        tech_map = {}
    if news_map is None:
        news_map = {}
    
    # 銘柄マッピング
    symbol_map = {
        "日本225": "JP225",
        "米国NQ100ミニ": "NAS100",
        "ドイツ40": "GER40",
        "金スポット": "XAUUSD"
    }
    
    results = []
    
    for jp_name, code in symbol_map.items():
        price = gmo_prices.get(jp_name)
        
        # 価格がない場合はスキップ
        if price is None or code not in tech_map:
            continue
        
        # テクニカル指標を取得
        t30, t240, _ = tech_map[code]
        
        # ニュースを取得
        news_text = news_map.get(jp_name, "")
        
        # 単一銘柄分析
        result = analyze_symbol(code, price, t30, t240, news_text)
        results.append(result)
    
    # DataFrame化
    if results:
        df = pd.DataFrame(results)
        return df
    else:
        return pd.DataFrame()


def format_html_table(df):
    """
    IFD結果をHTMLテーブルに変換
    """
    if df.empty:
        return "<p>No data</p>"
    
    html = "<table border='1' cellpadding='8' cellspacing='0'>"
    html += "<tr>"
    for col in df.columns:
        html += f"<th>{col}</th>"
    html += "</tr>"
    
    for _, row in df.iterrows():
        html += "<tr>"
        for val in row:
            html += f"<td>{val}</td>"
        html += "</tr>"
    
    html += "</table>"
    return html


# ====================================================
# 🧩 5. テスト実行
# ====================================================

if __name__ == "__main__":
    # ダミーデータで実行
    gmo_prices = {
        "日本225": 30000,
        "米国NQ100ミニ": 17500,
        "ドイツ40": 18000,
        "金スポット": 2400
    }
    
    tech_map = {
        "JP225": (
            {"sma25": 30050, "sma75": 30100, "macd": 0.5, "signal": 0.3, "rsi": 58, "atr": 150},
            {"sma25": 30100, "sma75": 29900, "macd": 1.2, "signal": 0.8, "rsi": 55, "atr": 200},
            {}
        ),
        "NAS100": (
            {"sma25": 17520, "sma75": 17500, "macd": 0.2, "signal": 0.1, "rsi": 52, "atr": 80},
            {"sma25": 17600, "sma75": 17400, "macd": 0.8, "signal": 0.5, "rsi": 54, "atr": 120},
            {}
        ),
        "GER40": (
            {"sma25": 18020, "sma75": 18010, "macd": 0.1, "signal": 0.05, "rsi": 50, "atr": 60},
            {"sma25": 18050, "sma75": 18000, "macd": 0.5, "signal": 0.3, "rsi": 52, "atr": 90},
            {}
        ),
        "XAUUSD": (
            {"sma25": 2405, "sma75": 2400, "macd": 0.3, "signal": 0.2, "rsi": 55, "atr": 15},
            {"sma25": 2410, "sma75": 2390, "macd": 1.0, "signal": 0.6, "rsi": 58, "atr": 25},
            {}
        )
    }
    
    news_map = {
        "日本225": "日本銀行が金利引き上げを発表。今後のインフレ対策が注目される。",
        "米国NQ100ミニ": "アップルが新製品を発表。テック企業の業績期待が高まる。",
        "ドイツ40": "ECBが金融政策の見直しを示唆。ユーロ相場に影響。",
        "金スポット": "インフレ懸念からゴールドへの投資需要が増加。"
    }
    
    df = analyze_unified_ifd(gmo_prices, tech_map, news_map)
    print(df)
