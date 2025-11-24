# -*- coding: utf-8 -*-
"""
あなた専用：CFD3 FastAPI ローカル運用版（2025/02 完成版）
- TradingView 方向アラート
- GMOスクショ → Vision価格補正
- 30m IFD & 4H IFD 自動生成
- 大量参戦モード（High Volatility Mode）
- ハイボラ判定（ATR / TV連発 / スクショ連打）
- 時間参戦（09:15 / 13:15 / 17:15 / 22:30）

実行例 (ローカル):
    uvicorn webhook_server:app --reload --port 8080
"""
from __future__ import annotations

from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Query
import time
from collections import deque
from datetime import datetime
from pathlib import Path
import json
import pandas as pd
from typing import Optional, Dict, Any
import base64
import subprocess
import sys
import logging
from openai import OpenAI
import io
import os

# ====== OpenAI ======
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# ====== ディレクトリ設定 ======
REPO = Path(__file__).resolve().parent
DATA_DIR = REPO / "data"
OUTPUT_DIR = REPO / "output"
LOGS_DIR = REPO / "logs"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ====== ロガー ======
logger = logging.getLogger("cfd3")
logging.basicConfig(level=logging.INFO)

# =====================================================================
# ニュース RSS 取得（Reuters / Bloomberg / CNBC / MarketWatch / ZeroHedge / FinancialJuice）
# =====================================================================
import feedparser
import requests
from bs4 import BeautifulSoup

RSS_SOURCES = [
    # 高信頼メディア
    ("Reuters Top News", "https://feeds.reuters.com/reuters/topNews"),
    ("Reuters World News", "https://feeds.reuters.com/Reuters/worldNews"),
    ("Bloomberg Markets", "https://www.bloomberg.com/feeds/podcast/etf-report.xml"),
    ("CNBC Top News", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),

    # マーケット系
    ("MarketWatch", "https://feeds2.feedburner.com/marketwatch/topstories"),
    ("FinancialJuice", "https://financialjuice.com/home/rss"),

    # クラッシュ系
    ("ZeroHedge", "https://zerohedge.com/fullrss"),
]


def fetch_rss_news(max_items: int = 40):
    """
    RSSニュースを最大40件まとめて取得する
    """
    all_news = []

    for source_name, url in RSS_SOURCES:
        try:
            feed = feedparser.parse(url)

            for entry in feed.entries[:10]:
                all_news.append({
                    "source": source_name,
                    "title": entry.get("title", "").strip(),
                    "summary": entry.get("summary", "").strip(),
                    "published": entry.get("published", ""),
                    "link": entry.get("link", "")
                })

        except Exception as e:
            logger.warning(f"RSS取得失敗: {source_name} - {e}")

    # 最新ニュース順にソート
    def sort_key(x):
        return x.get("published", "")

    all_news = sorted(all_news, key=sort_key, reverse=True)

    # 最大 max_items 件に制限
    return all_news[:max_items]

# =====================================================================
# ニュース スクレイピング（FinancialJuice / FXStreet / Investing / MarketWatch）
# =====================================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
}

def scrape_financialjuice():
    """
    FinancialJuice 速報ニュースをスクレイピング
    """
    url = "https://www.financialjuice.com/home"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        items = []
        for div in soup.select(".latest-news-item")[:10]:
            title = div.get_text(strip=True)
            items.append({
                "source": "FinancialJuice",
                "title": title,
                "summary": "",
                "link": url,
                "published": ""
            })
        return items
    except Exception as e:
        logger.warning(f"FinancialJuice scrape error: {e}")
        return []


def scrape_fxstreet():
    url = "https://www.fxstreet.com/news"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        items = []
        for div in soup.select(".fxs_headline_tiny")[:10]:
            title = div.get_text(strip=True)
            items.append({
                "source": "FXStreet",
                "title": title,
                "summary": "",
                "link": url,
                "published": ""
            })
        return items
    except Exception as e:
        logger.warning(f"FXStreet scrape error: {e}")
        return []


def scrape_investing():
    url = "https://www.investing.com/news/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        items = []
        for div in soup.select("article")[:10]:
            title = div.get_text(strip=True)
            items.append({
                "source": "Investing.com",
                "title": title,
                "summary": "",
                "link": url,
                "published": ""
            })
        return items
    except Exception as e:
        logger.warning(f"Investing scrape error: {e}")
        return []


def scrape_marketwatch():
    url = "https://www.marketwatch.com/latest-news"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        items = []
        for div in soup.select("h3.article__headline")[:10]:
            title = div.get_text(strip=True)
            items.append({
                "source": "MarketWatch",
                "title": title,
                "summary": "",
                "link": url,
                "published": ""
            })
        return items
    except Exception as e:
        logger.warning(f"MarketWatch scrape error: {e}")
        return []

# =====================================================================
# ニュース翻訳（英語 → 日本語：自然な日本語スタイル）
# =====================================================================

def translate_to_japanese(text: str) -> str:
    """
    AIを使って自然な日本語へ翻訳する（Aスタイル：読みやすく自然）
    """
    if not text or text.strip() == "":
        return ""

    prompt = f"""
以下の英文を「自然で読みやすい日本語」に翻訳してください。
専門用語は優しく補足し、文章は読みやすく整えてください。

--- 英文 ---
{text}
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"Translation error: {e}")
        return text  # 翻訳失敗時は元のテキストを返す

# =====================================================================
# 統合AI：ニュース危険度スコアリング
# =====================================================================

def score_news_risk(news_items: list[str]) -> dict:
    """
    ニュースをスコア化（0〜100）
    - 危険ワード：-30〜-50
    - 重要経済指標：-20
    - FRB/金利：-10〜-30
    - 地政学：-20
    """
    risk = 0
    summary = []

    NEGATIVE_KEYWORDS = {
        "geopolitical": -30,
        "conflict": -40,
        "attack": -50,
        "inflation": -15,
        "rate hike": -20,
        "hike": -20,
        "yields surge": -20,
        "crash": -40,
        "recession": -35,
        "default": -25,
        "bank failure": -60
    }

    for text in news_items:
        t = text.lower()
        for k, v in NEGATIVE_KEYWORDS.items():
            if k in t:
                risk += v
                summary.append(f"- {k}: {v}")

    # ニュースの危険スコアは -100〜+20 に収める
    risk = max(-100, min(20, risk))

    return {"risk": risk, "details": summary}


def collect_latest_news_for_symbol(symbol: str) -> dict:
    """
    symbolに関連するニュースを収集・翻訳して返す
    """
    # --- RSSから取得 ---
    rss_items = fetch_rss_news()

    # --- スクレイピングから取得 ---
    scrapes = []
    scrapes += scrape_financialjuice()
    scrapes += scrape_investing()
    scrapes += scrape_fxstreet()

    all_news = rss_items + scrapes

    # 銘柄に関係しやすい単語でフィルタ
    KEY_MAP = {
        "GER40": ["germany", "europe", "dax", "eurozone", "bundesbank"],
        "JP225": ["japan", "nikkei", "boj", "tokyo"],
        "NAS100": ["nasdaq", "us", "tech", "federal reserve"],
        "XAUUSD": ["gold", "precious metal", "xau"]
    }

    keywords = KEY_MAP.get(symbol.upper(), [])
    related = []

    for item in all_news:
        # ニュースitemは辞書形式なので、titleとsummaryを結合して検索
        txt = ""
        if isinstance(item, dict):
            txt = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        else:
            txt = str(item).lower()
        
        if any(k in txt for k in keywords):
            related.append(item)

    # 限定して最大10件
    related = related[:10]

    # 翻訳（タイトルのみ）
    translated = []
    for item in related:
        try:
            if isinstance(item, dict):
                title = item.get("title", "")
                jp = translate_to_japanese(title)
            else:
                jp = translate_to_japanese(str(item))
        except Exception:
            jp = str(item)
        translated.append(jp)

    # リスク評価（テキスト抽出）
    text_for_risk = []
    for item in related:
        if isinstance(item, dict):
            text_for_risk.append(f"{item.get('title', '')} {item.get('summary', '')}")
        else:
            text_for_risk.append(str(item))

    news_eval = score_news_risk(text_for_risk)

    return {
        "raw_news": related,
        "translated": translated,
        "risk": news_eval["risk"],
        "risk_details": news_eval["details"]
    }

# ====== ニュース取得 & AI分析 ======
try:
    from news_fetcher import fetch_latest_rss, fetch_x_market_news
    from ifd_analyzer import ai_ifd_analysis
    NEWS_ANALYSIS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"⚠️ news_fetcher or ifd_analyzer not available: {e}")
    NEWS_ANALYSIS_AVAILABLE = False
    def fetch_latest_rss(limit=5): return []
    def fetch_x_market_news(limit=5): return []
    def ai_ifd_analysis(ifd_data, rss_news, x_news): return {"error": "not_available"}

# ====== High Volatility Mode（大量参戦） ======
tv_alerts = deque(maxlen=20)        # TVアラート時刻
image_requests = deque(maxlen=20)   # スクショ解析時刻
recent_30m_trades = deque(maxlen=20)
high_volatility = False

# ====== TV の最新方向保存 ======
tv_last_direction = {}   # symbol → buy/sell
tv_last_signal = {}      # symbol → GO/STRONG_GO

# ====== TradingView CSV マップ ======
CSV_FILE_MAP = {
    "GER40": "FOREXCOM_GER40, 240.csv",
    "NAS100": "FOREXCOM_NAS100, 240.csv",
    "JP225": "FOREXCOM_JP225, 240.csv",
    "XAUUSD": "FOREXCOM_XAUUSD, 240.csv",
}

# =====================================================================
# テクニカル読込（ATR含む）
# =====================================================================
def load_latest_tech(symbol: str) -> Optional[Dict[str, float]]:
    sym = symbol.upper()
    fname = CSV_FILE_MAP.get(sym)
    if not fname:
        return None

    fp = DATA_DIR / fname
    if not fp.exists():
        return None

    df = pd.read_csv(fp)

    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"]).sort_values("time")

    df = df.tail(200).copy()
    close = df["close"]

    # ATR5 簡易計算
    atrs = [abs(close.iloc[i] - close.iloc[i - 1]) for i in range(-1, -6, -1)]
    atr5 = sum(atrs) / 5

    return {
        "close": float(close.iloc[-1]),
        "atr5": float(atr5),
        "recent_closes": [float(x) for x in close.tail(30)],
    }

# =====================================================================
# ハイボラ判定（ATR / TV連打 / スクショ連打）
# =====================================================================
def evaluate_high_volatility(symbol: str) -> bool:
    global high_volatility

    now = time.time()
    info = load_latest_tech(symbol)

    # ① ATR判定
    if info:
        atr = info["atr5"]
        sym = symbol.upper()
        if (sym == "GER40" and atr > 20) or \
           (sym == "NAS100" and atr > 30) or \
           (sym == "XAUUSD" and atr > 0.7):
            high_volatility = True
            logger.info(f"🔥 High volatility via ATR: {symbol} ATR5={atr}")
            return True

    # ② TVアラート 15分で3回以上
    recent_tv = [t for t in tv_alerts if now - t < 900]
    if len(recent_tv) >= 3:
        high_volatility = True
        logger.info(f"🔥 High volatility: {len(recent_tv)} TV alerts in 15min")
        return True

    # ③ スクショ 10分で2回以上
    recent_imgs = [t for t in image_requests if now - t < 600]
    if len(recent_imgs) >= 2:
        high_volatility = True
        logger.info(f"🔥 High volatility: {len(recent_imgs)} image requests in 10min")
        return True

    high_volatility = False
    return False

# =====================================================================
# GMOスクショ → Vision 解析
# =====================================================================
def analyze_image_with_ai(image_bytes: bytes, symbol_hint: str | None = None):
    b64 = base64.b64encode(image_bytes).decode()
    prompt = """
あなたはプロのトレーダーです。
画像から現在価格と方向、そしてエントリーを推定し、JSONのみ返してください。
{
 "symbol": "GER40",
 "direction": "buy",
 "entry": 23751.2,
 "confidence": 80,
 "comment": "..."
}
"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}
                    }
                ]
            }
        ],
        temperature=0.0
    )

    content = res.choices[0].message.content
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1]).strip()

    data = json.loads(content)
    if symbol_hint and (not data.get("symbol") or data.get("symbol") == "UNKNOWN"):
        data["symbol"] = symbol_hint

    return data

# =====================================================================
# Markdown フォーマット関数
# =====================================================================
def format_markdown_ifd(ifd_json):
    """
    IFD JSONをMarkdownテーブルに変換。
    """
    order = ifd_json["orders"][0]

    trade_mode = ifd_json.get("trade_mode", "-")
    symbol = order["instrument"]

    # direction を日本語化
    direction_jp = "買い" if order["direction"] == "buy" else "売り"

    entry = order["entry_order"]["price"]
    tp = order["ifd_legs"][0]["oco"]["take_profit"]["price"]
    sl = order["ifd_legs"][0]["oco"]["stop_loss"]["price"]

    # TP2（4H用）
    tp2 = "-"
    legs = order.get("ifd_legs", [])
    if len(legs) > 1:
        tp2 = legs[1]["oco"]["take_profit"]["price"]
    else:
        tp2 = ifd_json.get("tp2_price", "-")

    decision = order.get("decision", "-")
    lots = order.get("lots", 1)

    markdown = f"""
| trade_mode | 銘柄 | 方向 | entry_price | SL | TP1 | TP2 | order_type | 判定 | ニュースロック | 推奨度 | ロット | CUT条件 |
|------------|------|------|-------------|------|------|------|------------|--------|----------------|----------|--------|-----------|
| {trade_mode} | {symbol} | {direction_jp} | {entry} | {sl} | {tp} | {tp2} | 指値 | {decision} | false | ★★★★★ | {lots} | SMA25 < SMA75 または MACD < Signal |
"""
    return markdown

# =====================================================================
# IFD生成（30m：manual30_ifd を使用）
# =====================================================================
try:
    from manual30_ifd import generate_ifd as generate_manual30
    MANUAL30_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ manual30_ifd not found, using fallback")
    MANUAL30_AVAILABLE = False
    
    def generate_manual30(symbol, direction, entry, signal):
        """Fallback IFD generator"""
        return {
            "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "symbol": symbol,
            "direction": direction,
            "entry": entry,
            "signal": signal,
            "orders": [],
            "error": "manual30_ifd module not available"
        }

# =====================================================================
# FastAPI 本体
# =====================================================================
app = FastAPI(title="CFD3 Local Trade System")

# CORSミドルウェア追加（UI 8081 からのクロスオリジン許可）
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================================
# ルート
# =====================================================================
@app.get("/")
def root():
    """ウェルカムメッセージとエンドポイント一覧"""
    return {
        "service": "CFD3 Local Trade System",
        "version": "2025.02",
        "status": "running",
        "endpoints": {
            "POST /analyze/image": "GMOスクショ解析 + 30m IFD生成 + AI分析",
            "POST /webhook": "TradingView 方向アラート受信",
            "GET /health": "システム状態確認",
            "POST /debug/reset": "状態リセット（テスト用）"
        },
        "high_volatility": high_volatility,
        "manual30_available": MANUAL30_AVAILABLE,
        "news_analysis_available": NEWS_ANALYSIS_AVAILABLE
    }

# =====================================================================
# スクショ解析（エントリー作成）
# =====================================================================
@app.post("/analyze/image")
async def analyze_image(symbol: Optional[str] = None, file: UploadFile = File(...)):
    """
    GMOスクショから価格を読み取り、TV方向と組み合わせて30m IFD生成。
    ハイボラ判定により参戦制限を適用。
    """
    img = await file.read()
    if not img:
        raise HTTPException(status_code=400, detail="no image")

    # 記録（ハイボラ判定の材料）
    image_requests.append(time.time())
    logger.info(f"📸 Image request recorded (recent: {len(image_requests)})")

    # Vision解析
    analysis = analyze_image_with_ai(img, symbol_hint=symbol)

    sym = analysis["symbol"].upper()
    entry = float(analysis["entry"])
    direction = analysis["direction"]

    # 方向は最新TV方向を優先
    if sym in tv_last_direction:
        direction = tv_last_direction[sym]
        logger.info(f"🎯 Using TV direction for {sym}: {direction}")

    # High Vol 判定
    is_hv = evaluate_high_volatility(sym)

    # 低ボラ → 10分で1回制限
    if not is_hv:
        now = time.time()
        recent = [t for t in recent_30m_trades if now - t < 600]
        if len(recent) >= 1:
            logger.warning(f"⚠️ Low volatility: blocking {sym} (recent trades: {len(recent)})")
            return {
                "status": "blocked_low_vol",
                "message": "Low Volatility のため参戦制限（10分で1回まで）",
                "analysis": analysis,
                "high_volatility": False,
                "recent_trades": len(recent)
            }

    # トレード登録
    recent_30m_trades.append(time.time())

    # 自信度で signal切替
    conf = int(analysis.get("confidence") or 0)
    signal = "STRONG_GO" if conf >= 70 else "GO"

    # IFD生成
    ifd = generate_manual30(sym, direction, entry, signal)

    # JSON保存
    try:
        run_id = ifd.get("run_id") or datetime.now().strftime("%Y%m%d_%H%M%S")
        out_fp = OUTPUT_DIR / f"ifd_30m_{run_id}.json"
        with open(out_fp, "w", encoding="utf-8") as f:
            json.dump(ifd, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 IFD saved: {out_fp}")
    except Exception as e:
        logger.exception(f"Failed to save IFD: {e}")

    # ====== ニュース取得 & AI分析 ======
    ai_result = None
    if NEWS_ANALYSIS_AVAILABLE:
        try:
            logger.info("📰 Fetching news...")
            rss_news = fetch_latest_rss(limit=3)
            x_news = fetch_x_market_news(limit=3)
            
            logger.info(f"🤖 Running AI analysis... (RSS: {len(rss_news)}, X: {len(x_news)})")
            ai_analysis = ai_ifd_analysis(
                ifd_data=json.dumps(ifd, ensure_ascii=False),
                rss_news=json.dumps(rss_news, ensure_ascii=False),
                x_news=json.dumps(x_news, ensure_ascii=False)
            )
            
            # JSON形式のレスポンスをパース
            if ai_analysis.startswith("```"):
                lines = ai_analysis.split("\n")
                ai_analysis = "\n".join(lines[1:-1]).strip()
            
            try:
                ai_result = json.loads(ai_analysis)
                logger.info(f"✅ AI analysis complete: {ai_result.get('final_judgement', 'N/A')}")
            except json.JSONDecodeError:
                ai_result = {"raw_response": ai_analysis}
                logger.warning("⚠️ AI response not valid JSON, storing as raw")
        except Exception as e:
            logger.exception(f"AI analysis failed: {e}")
            ai_result = {"error": str(e)}

    return {
        "status": "ok",
        "high_volatility": is_hv,
        "analysis": analysis,
        "ifd": ifd,
        "recent_trades": len(recent_30m_trades),
        "ai_analysis": ai_result
    }

# =====================================================================
# TV Webhook（方向とsignalを更新）
# =====================================================================
@app.post("/webhook")
async def webhook(request: Request):
    """
    TradingView アラートから方向とシグナルを受信・保存。
    
    期待するJSON:
    {
      "symbol": "GER40",
      "direction": "buy",
      "signal": "STRONG_GO",
      "timeframe": "4H"  (optional)
    }
    """
    data = await request.json()

    symbol = data.get("symbol")
    direction = data.get("direction")
    signal = data.get("signal")

    if symbol and direction:
        symbol_upper = symbol.upper()
        tv_last_direction[symbol_upper] = direction.lower()
        tv_last_signal[symbol_upper] = (signal or "GO").upper()

        # TVアラート記録
        tv_alerts.append(time.time())
        logger.info(f"📡 TV alert: {symbol_upper} → {direction} / {signal or 'GO'} (recent: {len(tv_alerts)})")

        # ハイボラ判定実行
        is_hv = evaluate_high_volatility(symbol_upper)
        logger.info(f"📊 High volatility status: {is_hv}")

        return {
            "status": "tv_updated",
            "symbol": symbol_upper,
            "direction": direction,
            "signal": signal or "GO",
            "high_volatility": is_hv,
            "recent_alerts": len(tv_alerts)
        }

    return {"status": "ignored", "message": "Missing symbol or direction"}

# =====================================================================
# ニュースエンドポイント
# =====================================================================
@app.get("/news/rss")
async def news_rss():
    """
    RSSニュース（英語40件）を返す
    """
    items = fetch_rss_news()
    return {
        "count": len(items),
        "news": items,
    }

@app.get("/news/scrape")
async def news_scrape():
    """
    スクレイピング速報ニュースを返す
    """
    result = []
    result.extend(scrape_financialjuice())
    result.extend(scrape_fxstreet())
    result.extend(scrape_investing())
    result.extend(scrape_marketwatch())

    return {
        "count": len(result),
        "news": result[:40]
    }

@app.get("/news/translate")
def api_translate_news(
    text: str = Query(..., description="英語のニュース本文または見出し")
):
    """
    ニュース文章(英文)を自然な日本語へ翻訳して返すAPI。
    """
    if not text:
        return {"error": "text is empty"}

    translated = translate_to_japanese(text)
    return {
        "original": text,
        "translated": translated
    }

# =====================================================================
# 統合AI：画像 + ニュース + TV の総合判定
# =====================================================================

@app.post("/analyze/combined")
async def analyze_combined(file: UploadFile = File(...)):
    """
    Vision画像 + ニュースAI + TV方向 を統合した最終判定（B：バランス仕様）
    """
    img_bytes = await file.read()

    # Vision解析
    vision = analyze_image_with_ai(img_bytes)
    symbol = vision["symbol"]
    direction = vision["direction"]
    entry = float(vision["entry"])

    # TV方向の反映
    if symbol in tv_last_direction:
        direction = tv_last_direction[symbol]

    # ニュース取得
    news = collect_latest_news_for_symbol(symbol)
    news_risk = news["risk"]

    # 統合スコア（B：バランス）
    base_score = 50
    score = base_score + vision["confidence"] * 0.5 + news_risk * 0.2

    # 最終判定
    if score < 30:
        final = "STOP"
    elif score < 60:
        final = "GO"
    else:
        final = "STRONG_GO"

    # IFD生成
    if final != "STOP":
        ifd = generate_manual30(symbol, direction, entry, final)
    else:
        ifd = {"status": "blocked", "reason": "STOP (news risk high)"}

    return {
        "symbol": symbol,
        "vision": vision,
        "news": news,
        "news_risk": news_risk,
        "final_score": score,
        "final_judgement": final,
        "ifd": ifd
    }

# =====================================================================
# ヘルスチェック
# =====================================================================
@app.get("/health")
def health():
    """システム状態を返す"""
    return {
        "status": "running",
        "high_volatility": high_volatility,
        "tv_last_direction": tv_last_direction,
        "tv_last_signal": tv_last_signal,
        "recent_30m_trades": len(recent_30m_trades),
        "recent_tv_alerts": len(tv_alerts),
        "recent_image_requests": len(image_requests),
        "manual30_available": MANUAL30_AVAILABLE,
        "news_analysis_available": NEWS_ANALYSIS_AVAILABLE,
    }

# =====================================================================
# デバッグ：状態リセット
# =====================================================================
@app.post("/debug/reset")
def debug_reset():
    """テスト用：全状態をリセット"""
    global high_volatility
    tv_alerts.clear()
    image_requests.clear()
    recent_30m_trades.clear()
    tv_last_direction.clear()
    tv_last_signal.clear()
    high_volatility = False
    
    return {"status": "reset", "message": "All state cleared"}


# ====== 起動メモ ======
# ローカル起動例:
#   uvicorn webhook_server:app --reload --port 8080
