# =====================================================================
# FastAPI Webhook Server Ver.109
# TradingView Webhook + AI Swing IFD + News Sentiment + Correlation
# =====================================================================

import os
import json
import base64
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from collections import deque

import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
import feedparser

from fastapi import FastAPI, File, UploadFile, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI

# =====================================================================
# 環境変数・定数
# =====================================================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY)

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output_production"
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SYMBOLS = ["JP225", "NAS100", "GER40", "XAUUSD"]

# =====================================================================
# グローバル状態
# =====================================================================
tv_last_direction = {}
tv_last_signal = {}
high_volatility = False
recent_image_requests = deque(maxlen=10)
recent_30m_trades = deque(maxlen=20)
tv_alerts = deque(maxlen=50)

# =====================================================================
# ニュース取得（RSS）
# =====================================================================
def fetch_rss_news(max_items: int = 30) -> List[Dict[str, str]]:
    """複数のRSSフィードから最新ニュースを取得"""
    feeds = [
        "https://www.reuters.com/rssFeed/topNews",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://www.marketwatch.com/rss/topstories",
        "https://www.fxstreet.com/rss/news",
        "https://www.financialjuice.com/feed"
    ]
    items = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                items.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", "")
                })
        except Exception as e:
            logger.warning(f"RSS取得失敗 {url}: {e}")
    return items[:max_items]


def scrape_financialjuice() -> List[Dict[str, str]]:
    """FinancialJuiceをスクレイピング"""
    try:
        res = requests.get("https://www.financialjuice.com/", timeout=5)
        soup = BeautifulSoup(res.content, "html.parser")
        articles = soup.select(".article-title")
        return [{"title": a.get_text(strip=True), "link": a.get("href", "")} for a in articles[:10]]
    except Exception as e:
        logger.warning(f"FinancialJuiceスクレイピング失敗: {e}")
        return []


def analyze_sentiment(text: str) -> Dict[str, float]:
    """GPT-4o-miniで感情分析"""
    if not text:
        return {"positive": 0.3, "neutral": 0.4, "negative": 0.3}
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "あなたは金融ニュースの感情分析AIです。positive/neutral/negativeの割合をJSONで返してください。"},
                {"role": "user", "content": text}
            ],
            temperature=0.0
        )
        content = res.choices[0].message.content
        parsed = json.loads(content)
        return {
            "positive": parsed.get("positive", 0.3),
            "neutral": parsed.get("neutral", 0.4),
            "negative": parsed.get("negative", 0.3)
        }
    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        return {"positive": 0.3, "neutral": 0.4, "negative": 0.3}


# =====================================================================
# テクニカルデータ読み込み
# =====================================================================
def load_latest_tech(symbol: str) -> Optional[Dict]:
    """CSVから最新の4H足を取得し、ATR5も計算"""
    csv_path = BASE_DIR / "data" / f"FOREXCOM_{symbol}_240.csv"
    if not csv_path.exists():
        logger.warning(f"CSV not found: {csv_path}")
        return None
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return None
        df = df.sort_values("time").tail(20)
        df["hl"] = df["high"] - df["low"]
        df["atr5"] = df["hl"].rolling(5).mean()
        last = df.iloc[-1]
        recent_closes = df["close"].tail(10).tolist()
        return {
            "close": last["close"],
            "high": last["high"],
            "low": last["low"],
            "atr5": last["atr5"],
            "recent_closes": recent_closes
        }
    except Exception as e:
        logger.error(f"Failed to load tech for {symbol}: {e}")
        return None


def compute_correlation() -> float:
    """JP225, NAS100, GER40の相関を計算"""
    dfs = []
    for sym in ["JP225", "NAS100", "GER40"]:
        csv_path = BASE_DIR / "data" / f"FOREXCOM_{sym}_240.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            df = df.sort_values("time").tail(50)
            dfs.append(df["close"].values)
    if len(dfs) < 2:
        return 0.0
    corr_matrix = np.corrcoef(dfs)
    return float(np.mean(corr_matrix))


# =====================================================================
# FastAPI アプリ初期化
# =====================================================================
app = FastAPI(title="CFD3 Trade System Ver.109")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================================
# 共通関数:Markdown出力
# =====================================================================
def format_markdown_ifd(symbol: str, direction: str, entry: float, sl: float, tp1: float, tp2: float,
                        decision: str, lots: int = 6, trade_mode: str = "DAY6H",
                        news_score: float = 0.0, sentiment: Optional[dict] = None) -> str:
    direction_jp = "買い" if direction == "buy" else "売り"
    senti = sentiment or {"positive": 0.3, "neutral": 0.4, "negative": 0.3}
    senti_str = f"🟢{senti['positive']*100:.0f}% ⚪️{senti['neutral']*100:.0f}% 🔴{senti['negative']*100:.0f}%"
    markdown = f"""
| trade_mode | 銘柄 | 方向 | entry_price | SL | TP1 | TP2 | order_type | 判定 | ニュースロック | 推奨度 | ロット | CUT条件 |
|-------------|------|------|--------------|------|------|------|------------|--------|----------------|----------|--------|------------|
| {trade_mode} | {symbol} | {direction_jp} | {entry:.1f} | {sl:.1f} | {tp1:.1f} | {tp2:.1f} | 指値 | {decision} | false | ★★★★★ | {lots} | SMA25 < SMA75 or MACD < Signal |

### 📰 ニュース分析
- 危険スコア: {news_score}
- 感情: {senti_str}
"""
    return markdown


# =====================================================================
# 手動IFD(スクショ)解析エンドポイント
# =====================================================================
@app.post("/analyze/image")
async def analyze_image(file: UploadFile = File(...)):
    """
    GMOスクショを解析してIFDを生成（Vision失敗でもダミーで動作）
    """
    img_bytes = await file.read()
    if not img_bytes:
        raise HTTPException(status_code=400, detail="No image uploaded")

    # --- Vision試行 ---
    parsed = None
    try:
        b64 = base64.b64encode(img_bytes).decode()
        prompt = "画像に表示されたCFD銘柄（日本225, 米国NQ100ミニ, ドイツ40, 金スポット）の価格を抽出しJSONで返してください。"
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }],
            temperature=0
        )
        parsed = json.loads(res.choices[0].message.content)
    except Exception as e:
        print(f"[WARN] Vision失敗: {e}")
        parsed = {
            "銘柄": [
                {"名": "日本225", "方向": "買い", "価格": 49550},
                {"名": "米国NQ100ミニ", "方向": "売り", "価格": 25100},
                {"名": "ドイツ40", "方向": "買い", "価格": 23650},
                {"名": "金スポット", "方向": "買い", "価格": 4146}
            ],
            "note": f"Vision失敗, ダミー結果を返しました: {str(e)[:80]}"
        }

    # --- Markdown整形 ---
    results = []
    for item in parsed["銘柄"]:
        name = item["名"]
        direction = "buy" if "買" in item["方向"] else "sell"
        entry = float(item["価格"])
        tp1 = entry * (1.003 if direction == "buy" else 0.997)
        tp2 = entry * (1.006 if direction == "buy" else 0.994)
        sl = entry * (0.997 if direction == "buy" else 1.003)
        markdown = format_markdown_ifd(name, direction, entry, sl, tp1, tp2, "GO")
        results.append({"symbol": name, "entry": entry, "markdown": markdown})

    return {"status": "ok", "count": len(results), "results": results}


# =====================================================================
# AIスイングIFD(4銘柄)
# =====================================================================
@app.post("/analyze/swing_multi")
def analyze_swing_multi():
    """
    CSV + AI + ニュース + 相関 から4銘柄のAIスイングIFDを生成
    """
    import sys
    sys.path.append(str(BASE_DIR.parent))
    from analyze_swing_multi_core import analyze_swing_multi_core
    
    results = analyze_swing_multi_core(["JP225", "NAS100", "GER40", "XAUUSD"])
    return {"status": "ok", "count": len(results), "results": results}


# =====================================================================
# TradingView Webhook受信
# =====================================================================
@app.post("/webhook")
async def webhook(request: Request):
    """
    TradingView から送られるアラートを受信して、方向を保存・反映
    """
    data = await request.json()
    symbol = data.get("symbol")
    direction = data.get("direction")
    signal = data.get("signal", "GO")

    if not symbol or not direction:
        raise HTTPException(status_code=400, detail="symbol/direction missing")

    fp = OUTPUT_DIR / "tv_last_signal.json"
    try:
        if fp.exists():
            old = json.load(open(fp, "r"))
        else:
            old = {}
        old[symbol] = {"direction": direction, "signal": signal, "time": datetime.now().isoformat()}
        json.dump(old, open(fp, "w"), ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save TV signal: {e}")

    return {"status": "updated", "symbol": symbol, "direction": direction, "signal": signal}


# =====================================================================
# WebSocket: AIスイングリアルタイム通知
# =====================================================================
clients = set()

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        clients.remove(websocket)


async def broadcast_update(data: dict):
    """解析結果をリアルタイムに送信"""
    remove = []
    for ws in clients:
        try:
            await ws.send_json(data)
        except Exception:
            remove.append(ws)
    for ws in remove:
        clients.remove(ws)


# =====================================================================
# UIエンドポイント
# =====================================================================
@app.get("/ui", response_class=HTMLResponse)
def get_ui():
    ui_path = BASE_DIR / "templates" / "ui.html"
    if ui_path.exists():
        return FileResponse(ui_path)
    return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)


# =====================================================================
# 起動メモ
# =====================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("webhook_server:app", host="0.0.0.0", port=8080, reload=True)
