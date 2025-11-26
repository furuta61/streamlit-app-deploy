# -*- coding: utf-8 -*-
"""
あなた専用：CFD3 AIスイングトレード版（gpt-4o / スクショ不要 / 完全ローカル対応）
------------------------------------------------------------
- TradingView webhookで方向・強度を受信
- ニュース・ATR・テクニカル要素をAI統合判断
- IFD生成＋Markdown出力
- FastAPI + Uvicornローカルサーバ（UI付き）
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
import pandas as pd
import feedparser, requests, json, time
from pathlib import Path
from datetime import datetime
import logging, os

# ====== OpenAI 初期化 ======
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = "gpt-4o"

# ====== 基本設定 ======
app = FastAPI(title="CFD3 AI Swing IFD System")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

REPO = Path(__file__).resolve().parent
DATA_DIR = REPO / "data"
OUTPUT_DIR = REPO / "output"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
logger = logging.getLogger("cfd3")
logging.basicConfig(level=logging.INFO)

# ====== グローバル状態 ======
tv_directions = {}
tv_signals = {}
high_volatility = {}
symbols = ["JP225", "NAS100", "GER40", "XAUUSD"]

# ====== ATR判定 ======
CSV_FILE_MAP = {
    "GER40": "FOREXCOM_GER40_240.csv",
    "NAS100": "FOREXCOM_NAS100_240.csv",
    "JP225": "FOREXCOM_JP225_240.csv",
    "XAUUSD": "FOREXCOM_XAUUSD_240.csv"
}

def load_atr(symbol):
    fp = DATA_DIR / CSV_FILE_MAP.get(symbol, "")
    if not fp.exists():
        return None
    df = pd.read_csv(fp)
    close = df["close"].tail(20)
    atr = abs(close.diff()).tail(5).mean()
    return float(atr)

# ====== ニュース収集 ======
RSS = [
    "https://feeds.reuters.com/reuters/topNews",
    "https://feeds2.feedburner.com/marketwatch/topstories",
    "https://financialjuice.com/home/rss"
]
def fetch_news():
    items = []
    for url in RSS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:10]:
                items.append(e.title)
        except:
            pass
    return items

# ====== ニュースリスク算出 ======
def score_news(news_list):
    NEG = {"crash": -50, "recession": -40, "inflation": -20, "war": -50, "attack": -40, "default": -30}
    score = 0
    for n in news_list:
        for k, v in NEG.items():
            if k in n.lower():
                score += v
    return max(-100, min(20, score))

# ====== AI統合判定 ======
def ai_ifd_analysis(symbol, atr, tv_dir, tv_sig, news_list):
    news_summary = " / ".join(news_list[:5])
    prompt = f"""
あなたはプロの金融AIアナリストです。
以下の要素をもとにスイングトレードIFD戦略を提案してください。

銘柄: {symbol}
ATR: {atr}
方向: {tv_dir}
シグナル強度: {tv_sig}
ニュース: {news_summary}

出力フォーマット:
JSONのみで出力してください:
{{
 "symbol": "{symbol}",
 "direction": "buy/sell",
 "entry": 数値,
 "take_profit": 数値,
 "stop_loss": 数値,
 "confidence": 0〜100,
 "comment": "説明",
 "markdown": "Markdownテーブル1枚"
}}
"""
    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        txt = res.choices[0].message.content
        if "```" in txt:
            txt = txt.split("```")[1].replace("json","").strip()
        return json.loads(txt)
    except Exception as e:
        return {"error": str(e)}

# ====== Webhook (TradingViewから方向を受信) ======
@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    sym = data.get("symbol", "").upper()
    if sym not in symbols:
        return {"error": "unknown symbol"}
    tv_directions[sym] = data.get("direction", "buy")
    tv_signals[sym] = data.get("signal", "GO")
    return {"status": "updated", "tv_directions": tv_directions}

# ====== AI IFD生成 ======
@app.get("/analyze/swing")
def analyze_swing():
    results = []
    news = fetch_news()
    risk = score_news(news)

    for sym in symbols:
        atr = load_atr(sym)
        tv_dir = tv_directions.get(sym, "buy")
        tv_sig = tv_signals.get(sym, "GO")
        ai_res = ai_ifd_analysis(sym, atr, tv_dir, tv_sig, news)
        ai_res["news_risk"] = risk
        results.append(ai_res)

    out_fp = OUTPUT_DIR / f"swing_ifd_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_fp, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return {
        "status": "ok",
        "model": MODEL,
        "count": len(results),
        "news_risk": risk,
        "results": results
    }

# ====== ヘルスチェック ======
@app.get("/health")
def health():
    return {"status": "running", "tv": tv_directions, "symbols": symbols}

# ====== UI ======
@app.get("/ui")
def ui():
    return {
        "message": "CFD3 Swing IFD UI起動中",
        "urls": {
            "webhook": "POST /webhook",
            "analyze": "GET /analyze/swing",
            "health": "GET /health"
        }
    }

# ====== 実行方法 ======
# 1. pip install -r requirements.txt
# 2. uvicorn webhook_server:app --reload --port 8080
# 3. ngrok http 8080 でスマホからアクセス可
