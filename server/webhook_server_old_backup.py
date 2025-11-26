# -*- coding: utf-8 -*-
"""
webhook_server.py
デイトレ + スイング完全統合版 + ニュース分析
"""

import logging
from typing import Dict, Any, List

from openai import OpenAI
from server.ai_swing_master import analyze_swing

# ニュース取得用
try:
    import feedparser
    import requests
    from bs4 import BeautifulSoup
    NEWS_AVAILABLE = True
except ImportError:
    NEWS_AVAILABLE = False
    logging.warning("⚠️ ニュース機能無効（feedparser/requests/bs4が必要）")

# 手動30m IFD（デイトレ版）
try:
    from manual30_ifd import generate_ifd as generate_manual30
    MANUAL30_AVAILABLE = True
except:
    MANUAL30_AVAILABLE = False

client = OpenAI()
logger = logging.getLogger("webhook")

BASE_DIR = Path(__file__).resolve().parents[1]
UI_DIR = BASE_DIR / "ui"
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ニュースRSSフィード
RSS_FEEDS = [
    ("Reuters", "https://feeds.reuters.com/reuters/topNews"),
    ("MarketWatch", "https://feeds2.feedburner.com/marketwatch/topstories"),
    ("ZeroHedge", "https://zerohedge.com/fullrss"),
]

# TV方向記憶用（TradingViewアラートから更新）
tv_last_direction = {}  # symbol → "buy" or "sell"
tv_last_signal = {}     # symbol → "GO" or "STRONG_GO"

# CSV マップ
CSV_FILE_MAP = {
    "GER40": "FOREXCOM_GER40_240.csv",
    "NAS100": "FOREXCOM_NAS100_240.csv",
    "JP225": "FOREXCOM_JP225_240.csv",
    "XAUUSD": "FOREXCOM_XAUUSD_240.csv",
}

# ==============================
# ニュース取得関数
# ==============================
def fetch_news_headlines(max_items: int = 10) -> List[Dict[str, str]]:
    """RSSから最新ニュースを取得（非同期処理推奨だが簡易版）"""
    if not NEWS_AVAILABLE:
        return []
    
    all_news = []
    for name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                all_news.append({
                    "source": name,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:200]
                })
                if len(all_news) >= max_items:
                    break
        except Exception as e:
            logger.warning(f"RSS {name} fetch failed: {e}")
    
    return all_news[:max_items]

def translate_headlines(headlines: List[str]) -> List[str]:
    """ニュース見出しを日本語に翻訳（簡易版・コスト注意）"""
    if not headlines:
        return []
    
    try:
        prompt = "以下の英語ニュースを日本語に簡潔に翻訳:\n" + "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=300
        )
        content = res.choices[0].message.content.strip()
        return content.split("\n")
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return headlines


def collect_latest_news_for_symbol(symbol: str) -> dict:
    """銘柄に関連するニュースを収集・翻訳して返す"""
    news_raw = fetch_news_headlines(max_items=10)
    news_titles = [n["title"] for n in news_raw]
    translated = translate_headlines(news_titles) if news_titles else []
    
    # 簡易リスクスコア（ネガティブワードカウント）
    risk = 0
    negative_words = ["inflation", "rate hike", "crash", "recession", "conflict", "default"]
    for title in news_titles:
        title_lower = title.lower()
        for word in negative_words:
            if word in title_lower:
                risk -= 10
    
    risk = max(-100, min(20, risk))
    
    return {
        "raw_news": news_raw,
        "translated": translated,
        "risk": risk,
        "risk_details": [f"危険度スコア: {risk}"]
    }


def load_latest_tech(symbol: str) -> dict:
    """テクニカルデータ読込（ATR5含む）"""
    import pandas as pd
    
    fname = CSV_FILE_MAP.get(symbol.upper())
    if not fname:
        logger.warning(f"CSV not found for {symbol}")
        return None
    
    fp = DATA_DIR / fname
    if not fp.exists():
        logger.warning(f"CSV file not exists: {fp}")
        return None
    
    try:
        df = pd.read_csv(fp)
        
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], errors="coerce")
            df = df.dropna(subset=["time"]).sort_values("time")
        
        df = df.tail(200).copy()
        close = df["close"]
        
        # ATR5簡易計算
        atrs = [abs(close.iloc[i] - close.iloc[i - 1]) for i in range(-1, -6, -1)]
        atr5 = sum(atrs) / 5 if atrs else 0
        
        return {
            "close": float(close.iloc[-1]),
            "atr5": float(atr5),
            "recent_closes": [float(x) for x in close.tail(30)],
        }
    except Exception as e:
        logger.error(f"load_latest_tech error: {e}")
        return None


def format_markdown_ifd(ifd_json: Dict, news_info: dict = None) -> str:
    """改良版 Markdown IFD テーブル生成"""
    try:
        order = ifd_json["orders"][0]
        trade_mode = ifd_json.get("trade_mode", "SWING_4H")
        symbol = order.get("instrument", "-")
        direction = order.get("direction", "buy")
        direction_jp = "買い" if direction == "buy" else "売り"
        
        entry = order["entry_order"]["price"]
        tp = order["ifd_legs"][0]["oco"]["take_profit"]["price"]
        sl = order["ifd_legs"][0]["oco"]["stop_loss"]["price"]
        decision = order.get("decision", "-")
        lots = order.get("lots", 6)
        
        markdown = f"""
### 📊 IFD注文データ

| trade_mode | 銘柄 | 方向 | entry_price | SL | TP1 | 判定 | 推奨度 | ロット | CUT条件 |
|-------------|------|------|--------------|------|------|------|----------|--------|------------|
| {trade_mode} | {symbol} | {direction_jp} | {entry} | {sl} | {tp} | {decision} | ★★★★★ | {lots} | SMA25 < SMA75 or MACD < Signal |

### 📰 ニュース分析
- 危険スコア: {news_info.get('risk', 0) if news_info else 0}
"""
        
        if news_info and news_info.get("translated"):
            for t in news_info["translated"][:3]:
                markdown += f"- {t}\n"
        
        markdown += "\n---\n"
        return markdown
    except Exception as e:
        logger.error(f"format_markdown_ifd error: {e}")
        return f"⚠️ Markdown生成エラー: {e}"

# ==============================
# FastAPI
# ==============================
app = FastAPI(title="CFD3 Full System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


@app.get("/ui", response_class=HTMLResponse)
def serve_ui():
    index_path = UI_DIR / "index.html"
    return index_path.read_text(encoding="utf-8")


# ==============================
# Vision：画像解析
# ==============================
def analyze_image_with_ai(image_bytes: bytes):
    b64 = base64.b64encode(image_bytes).decode()

    prompt = """
あなたはプロのトレーダーです。
以下の画像はGMOクリック証券のCFD画面です。

**重要**: 画面に表示されている数値（Bid, Askなど）をそのまま答えに含めず、
チャート形状・トレンド・相場全体の動きを読み取り、
銘柄名・方向・信頼度を推定してください。

銘柄は以下限定：
- GER40 (ドイツ40, Germany40, DAX40)
- JP225 (日経225)
- NAS100 (ナスダック100)
- XAUUSD (金/ドル)

必ずこの形式でJSONのみ返してください：

{
 "symbol": "JP225",
 "direction": "buy",
 "entry": 0,
 "confidence": 80,
 "comment": "チャート上昇トレンド継続、抵抗線突破済み"
}

- entry は 0 固定
- comment にチャート分析の根拠を記載
- JSON以外の出力は禁止
"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
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
        ]
    )

    txt = res.choices[0].message.content.strip()

    if txt.startswith("```"):
        txt = txt.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    return json.loads(txt)


# ==============================
# 1) デイトレ 30m 用エンドポイント
# ==============================
@app.post("/analyze/image")
async def analyze_image_endpoint(file: UploadFile = File(...)):
    img = await file.read()
    if not img:
        raise HTTPException(status_code=400, detail="No image")

    vision = analyze_image_with_ai(img)
    symbol = vision["symbol"]
    direction = vision["direction"]
    
    # entry=0 の場合はダミー価格を使用（IFD生成のため）
    entry = float(vision.get("entry", 0))
    if entry == 0:
        # ダミー価格（実際にはGMO画面から手動で確認する想定）
        dummy_prices = {
            "JP225": 48700.0,
            "NAS100": 24800.0,
            "GER40": 23400.0,
            "XAUUSD": 4140.0
        }
        entry = dummy_prices.get(symbol, 10000.0)
        logger.warning(f"[Daytrade] Entry=0 detected, using dummy price: {entry}")

    if MANUAL30_AVAILABLE:
        ifd = generate_manual30(symbol, direction, entry, "GO")
    else:
        ifd = {"error": "manual30_ifd missing"}
    
    # ニュース取得
    news_info = collect_latest_news_for_symbol(symbol)
    
    # Markdown生成（新形式に対応）
    markdown = ""
    if ifd.get("orders"):
        markdown = format_markdown_ifd(ifd, news_info)

    return {
        "mode": "daytrade_30m",
        "vision": vision,
        "ifd": ifd,
        "news": news_info,
        "markdown": markdown
    }


# ==============================
# 2) スイングAI（手動呼び出し）
# ==============================
@app.get("/analyze/swing")
def swing_api(symbol: str = "GER40"):
    result = analyze_swing(symbol)
    return {
        "mode": "swing",
        "result": result
    }


# ==============================
# 3) スマホスクショ → Swing IFD 自動生成
# ==============================
@app.post("/analyze/swing_from_image")
async def swing_from_image(file: UploadFile = File(...)):
    img_bytes = await file.read()
    vision = analyze_image_with_ai(img_bytes)

    symbol = vision["symbol"]
    swing = analyze_swing(symbol)

    if swing["final_direction"] == "STOP":
        return {
            "mode": "swing",
            "vision": vision,
            "swing": swing,
            "ifd": {"status": "STOP", "reason": swing["reason"]}
        }

    # IFD化
    ifd = {
        "symbol": symbol,
        "lots": 1,
        "entry": swing["entry_price"],
        "direction": swing["final_direction"].lower(),
        "tp": swing["tp_price"],
        "sl": swing["sl_price"],
        "hold_days": swing["hold_days"],
    }

    return {
        "mode": "swing_from_image",
        "vision": vision,
        "swing": swing,
        "ifd": ifd
    }


# ==============================
# 4) 4銘柄一括スイングAI解析（画像不要）
# ==============================
@app.post("/analyze/swing_multi")
async def analyze_swing_multi():
    """
    画像を使わずに、4銘柄のスイングIFDをAIが自動生成。
    TradingView方向 + テクニカル + ニュース + AI総合評価。
    """
    symbols = ["JP225", "NAS100", "GER40", "XAUUSD"]
    results = []

    for sym in symbols:
        logger.info(f"🔍 Processing {sym}...")
        
        # --- テクニカル読込 ---
        tech = load_latest_tech(sym)
        if not tech:
            logger.warning(f"⚠️ {sym}: テクニカルデータなし、スキップ")
            continue

        direction = tv_last_direction.get(sym, "buy")
        signal = tv_last_signal.get(sym, "GO")

        # --- ニュース解析 ---
        news_info = collect_latest_news_for_symbol(sym)
        risk = news_info["risk"]

        # --- テクニカル強度スコア ---
        atr_score = min(100, tech["atr5"] * 4)
        trend_score = 30 if direction == "buy" else 20  # 仮強度

        # --- 総合スコア ---
        score = 50 + atr_score * 0.1 + trend_score * 0.2 + risk * 0.3
        score = max(0, min(100, score))

        if score < 30:
            final = "STOP"
        elif score < 60:
            final = "GO"
        else:
            final = "STRONG_GO"

        # --- エントリー価格 ---
        entry = tech["close"]

        # --- IFD生成 ---
        if MANUAL30_AVAILABLE and final != "STOP":
            ifd = generate_manual30(sym, direction, entry, final)
        else:
            ifd = {"status": "blocked", "reason": f"{final} judgment"}

        # --- Markdown出力 ---
        markdown = ""
        if ifd.get("orders"):
            markdown = format_markdown_ifd(ifd, news_info)

        # --- ログ統合 ---
        results.append({
            "symbol": sym,
            "entry": entry,
            "direction": direction,
            "score": round(score, 1),
            "final_judgement": final,
            "atr": round(tech["atr5"], 2),
            "news_risk": risk,
            "ifd": ifd,
            "markdown": markdown
        })

    # --- AI全体コメント ---
    overall_summary = "\n".join([
        f"- {r['symbol']}: {r['final_judgement']} (score={r['score']})"
        for r in results
    ])

    return {
        "mode": "SWING_4H_AI_MULTI",
        "status": "ok",
        "summary": overall_summary,
        "count": len(results),
        "results": results
    }


# ==============================
# health
# ==============================
@app.get("/health")
def health():
    return {"status": "running"}


# ==============================
# マルチ銘柄検出テスト
# ==============================
@app.post("/analyze/multi_image")
async def analyze_multi_image(file: UploadFile = File(...)):
    """
    GMOスクショに複数銘柄（JP225, NAS100, GER40, XAUUSD）が写っている場合、
    それぞれの検出結果を出力。
    """
    img = await file.read()
    if not img:
        raise HTTPException(status_code=400, detail="No image provided")
    
    b64 = base64.b64encode(img).decode()
    
    prompt = """
画像にはJP225, NAS100, GER40, XAUUSDなど複数の銘柄が表示されています。
それぞれについて、次の形式でJSONを返してください：

[
 {"symbol": "JP225", "bid": 48737.2, "ask": 48739.6},
 {"symbol": "NAS100", "bid": 24889.3, "ask": 24890.0},
 {"symbol": "GER40", "bid": 23457.7, "ask": 23460.7},
 {"symbol": "XAUUSD", "bid": 4146.8, "ask": 4146.95}
]

重要：
- GER40 は「ドイツ40」「Germany40」「DAX40」などの表示名で写っている可能性があります
- すべての銘柄を必ず検出してください
- 画像に写っていない銘柄は省略してください
- bid/askの数値は小数点まで正確に読み取ってください
"""
    
    try:
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
            temperature=0,
            max_tokens=500
        )
        
        content = res.choices[0].message.content.strip()
        logger.info(f"[MultiVision] Raw response: {content[:200]}")
        
        # JSONブロック除去
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        
        data = json.loads(content)
        
        # 検出結果のサマリー
        detected_symbols = [item.get("symbol") for item in data]
        logger.info(f"[MultiVision] Detected symbols: {detected_symbols}")
        
        return {
            "mode": "multi_symbol_detection",
            "detected_count": len(data),
            "symbols": detected_symbols,
            "details": data
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"[MultiVision] JSON parse error: {e}")
        logger.error(f"[MultiVision] Raw content: {content}")
        raise HTTPException(status_code=500, detail=f"Vision JSON parse error: {e}")
    except Exception as e:
        logger.exception("[MultiVision] Unexpected error")
        raise HTTPException(status_code=500, detail=f"Multi-symbol detection error: {e}")


@app.post("/analyze/multi_image_news")
async def analyze_multi_image_news(file: UploadFile = File(...)):
    """
    GMOスクショから複数銘柄（JP225, NAS100, GER40, XAUUSD）の価格を抽出し、
    それぞれにニュース情報を付与して返す。
    """
    logger.info("[MultiNews] Starting multi-symbol with news analysis")
    
    img = await file.read()
    b64 = base64.b64encode(img).decode()

    # --- マルチ銘柄抽出 ---
    prompt = """
この画像には「JP225」「NAS100」「GER40」「XAUUSD」など複数の銘柄が表示されています。
それぞれの銘柄のBIDとASKを以下の形式でJSON配列で返してください：

[
  {"symbol": "JP225", "bid": 48737.2, "ask": 48739.6},
  {"symbol": "NAS100", "bid": 24889.3, "ask": 24890.0},
  {"symbol": "GER40", "bid": 23457.7, "ask": 23460.7},
  {"symbol": "XAUUSD", "bid": 4146.8, "ask": 4147.0}
]

GER40は「ドイツ40」「Germany40」「DAX40」などの別名でも表示される可能性があります。
JSON以外の出力は禁止です。
"""

    try:
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

        raw = res.choices[0].message.content.strip()
        logger.info(f"[MultiNews] Vision raw response: {raw[:200]}...")
        
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:-1]).strip()

        try:
            multi_data = json.loads(raw)
        except Exception as parse_err:
            logger.error(f"[MultiNews] JSON parse failed: {parse_err}")
            return {"error": "parse_failed", "raw": raw}

        # --- 各銘柄にニュースを追加 ---
        logger.info(f"[MultiNews] Fetching news for {len(multi_data)} symbols")
        
        # ニュースを一度だけ取得
        news_headlines = fetch_news_headlines(max_items=10)
        translated = translate_headlines(news_headlines)
        
        results = []
        for item in multi_data:
            sym = item["symbol"]
            logger.info(f"[MultiNews] Processing symbol: {sym}")
            
            # 各銘柄に同じニュースを付与（簡易版）
            # より高度な実装では銘柄別にニュースをフィルタリング可能
            results.append({
                "symbol": sym,
                "bid": item.get("bid"),
                "ask": item.get("ask"),
                "news": {
                    "translated": translated[:5],  # 上位5件
                    "total_count": len(translated)
                }
            })

        logger.info(f"[MultiNews] Successfully processed {len(results)} symbols")
        
        return {
            "status": "ok",
            "count": len(results),
            "symbols": [r["symbol"] for r in results],
            "results": results
        }
        
    except Exception as e:
        logger.exception("[MultiNews] Unexpected error")
        raise HTTPException(status_code=500, detail=f"Multi-image news error: {e}")


# 起動例:
# uvicorn server.webhook_server:app --reload --port 8080
