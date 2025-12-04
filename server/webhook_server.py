# -*- coding: utf-8 -*-
"""
CFD3 DawnAI — Ver.200 (FIXED)
ハイブリッド IFD（Vision価格 × テクニカル × ニュース × GPT判定）
完全修正版
"""

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR.parent))

import os, json, random, base64, logging
import pandas as pd
import numpy as np
from datetime import datetime
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

DATA_DIR = BASE_DIR / "data"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CFD3 FIXED")

# ------------------------------------------------------------
# 前処理（インジ無視・OHLC だけ抽出）
# ------------------------------------------------------------

def clean_dataframe(df, symbol=None):
    keep = ["time", "open", "high", "low", "close"]
    df = df[keep].copy()

    for c in keep:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna()

    if len(df) < 100:
        raise ValueError(f"{symbol}: CSV行数不足（{len(df)}）")

    return df

# ------------------------------------------------------------
# テクニカル（落ちない安全仕様）
# ------------------------------------------------------------

def calc_tech(df):
    df = df.copy()
    df = df.dropna(subset=["open","high","low","close"])

    close = df["close"].astype(float)

    if len(close) < 100:
        raise ValueError("行数が不足")

    sma25 = close.rolling(25).mean().iloc[-1]
    sma75 = close.rolling(75).mean().iloc[-1]

    if np.isnan(sma25): sma25 = close.iloc[-1]
    if np.isnan(sma75): sma75 = close.iloc[-1]

    macd = close.ewm(span=12).mean().iloc[-1] - close.ewm(span=26).mean().iloc[-1]
    signal = (close.ewm(span=12).mean() - close.ewm(span=26).mean()).ewm(span=9).mean().iloc[-1]

    if np.isnan(macd): macd = 0
    if np.isnan(signal): signal = 0

    diff = close.diff()
    gain = diff.clip(lower=0).rolling(14).mean()
    loss = diff.clip(upper=0).abs().rolling(14).mean()
    rsi = 100 - 100 / (1 + (gain / loss))

    rsi_val = rsi.iloc[-1]
    if np.isnan(rsi_val):
        rsi_val = 50

    atr = close.diff().abs().rolling(14).mean().iloc[-1]
    if np.isnan(atr):
        atr = (close.max() - close.min()) * 0.01

    return {
        "close": close.iloc[-1],
        "sma25": sma25,
        "sma75": sma75,
        "macd": macd,
        "signal": signal,
        "rsi": rsi_val,
        "atr": atr
    }

# ------------------------------------------------------------
# ニュース感情（ダミー実装 - 外部依存削除）
# ------------------------------------------------------------

def analyze_news_sentiment(news_text: str = ""):
    """ニュース感情分析（ダミー実装）"""
    return {"positive": 50, "negative": 50, "summary": news_text}

# ------------------------------------------------------------
# Weighted × GPT の Meta 判定
# ------------------------------------------------------------

def weighted_direction(t30, t240, news, price):
    score_4h = (1 if t240["sma25"] > t240["sma75"] else -1) + \
               (1 if t240["close"] > t240["sma25"] else -1)

    score_30 = (1 if t30["rsi"] > 55 else -1 if t30["rsi"] < 45 else 0) + \
               (1 if t30["macd"] > t30["signal"] else -1)

    score_news = (news["positive"] - news["negative"]) / 20
    score_gmo = 1 if price > t30["sma25"] else -1

    final = score_4h*0.45 + score_30*0.25 + score_news*0.15 + score_gmo*0.15

    if final > 0.8: return "buy", final
    if final < -0.8: return "sell", final
    return "stop", final

def meta_decision(t30, t240, news, price, gpt_dir):
    w_dir, score = weighted_direction(t30, t240, news, price)

    long_dir = "buy" if t240["sma25"] > t240["sma75"] else "sell"
    if abs(score) > 1.5:
        return long_dir, score, "4H強トレンド優先"

    if price > t30["sma25"] * 1.002:
        return "buy", score, "GMO強上抜け"
    if price < t30["sma25"] * 0.998:
        return "sell", score, "GMO強下抜け"

    if abs(score) < 0.8:
        return "stop", score, "中立 → HOLD"

    if gpt_dir == w_dir:
        return w_dir, score + 0.3, "GPT一致 → 強化"

    return w_dir, score, "GPT矛盾 → Weighted優先"

# ------------------------------------------------------------
# GPTコメント付き Dawn 判定
# ------------------------------------------------------------

def dawn_ai_decision(symbol, t30, t240, news, price):
    prompt = f"""
銘柄: {symbol}
30分 RSI {t30['rsi']:.1f}, MACD {t30['macd']:.2f}
4H SMA25 {t240['sma25']:.1f}, SMA75 {t240['sma75']:.1f}
ニュース: +{news['positive']} / -{news['negative']}
GMO価格: {price}
buy / sell / stop で返答。
"""
    try:
        gpt_raw = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0.1
        )
        gpt_dir = gpt_raw.choices[0].message.content.strip().lower()
        if gpt_dir not in ["buy","sell","stop"]:
            gpt_dir="stop"
    except:
        gpt_dir="stop"

    final_dir, score, reason = meta_decision(t30, t240, news, price, gpt_dir)
    confidence = int(min(100, max(0, 50 + abs(score)*25)))

    return {
        "direction": final_dir,
        "comment": f"{reason.replace('→',' → ')}",
        "confidence": confidence
    }

# ------------------------------------------------------------
# 強度判定 / 品質ゲート 拡張
# ------------------------------------------------------------

from typing import Dict, Tuple, Optional
import time as _time

# Gateしきい値
GATE_MAX_AGE_SEC   = 90
GATE_MAX_DRIFT_PCT = 0.0008   # 0.08%
GATE_MIN_OCR_CONF  = 0.98

def data_quality_gate(vision: Dict, ref_price: float) -> Tuple[bool, str]:
    """
    GMOスクショ由来の現在値が妥当かを確認。
    vision: {"price": float, "ts": epoch_sec, "ocr_conf": float}
    ref_price: feed_price等の比較対象
    """
    if not vision or "price" not in vision:
        return False, "DATA_NG: missing_vision_price"
    price = float(vision.get("price", 0.0))
    ts    = float(vision.get("ts", 0.0))
    conf  = float(vision.get("ocr_conf", 0.0))

    # 1) 時間
    age = abs(_time.time() - ts) if ts > 0 else 1e9
    if age > GATE_MAX_AGE_SEC:
        return False, f"DATA_NG: stale({int(age)}s)"

    # 2) 価格乖離
    if ref_price > 0:
        drift = abs(price - ref_price) / ref_price
        if drift > GATE_MAX_DRIFT_PCT:
            return False, f"DATA_NG: drift({drift:.4%})"

    # 3) OCR信頼度
    if conf < GATE_MIN_OCR_CONF:
        return False, f"DATA_NG: ocr_conf({conf:.2f})"

    return True, "DATA_OK"

def direction_votes(long_dir: str, weighted_dir: str, gpt_dir: str, tv_dir: str, gmo_bias_dir: str) -> Tuple[str, int]:
    """最頻値による方向コンセンサス"""
    dirs = [d for d in [long_dir, weighted_dir, gpt_dir, tv_dir, gmo_bias_dir] if d in ("buy","sell")]
    if not dirs:
        return "stop", 0
    # 最頻値
    from collections import Counter
    c = Counter(dirs).most_common(1)[0]
    majority_dir, count = c[0], c[1]
    return majority_dir, count

def gmo_bias_direction(gmo_price: float, sma25_30: float, up_mult=1.0015, dn_mult=0.9985) -> str:
    """GMO価格のSMA25からの乖離で方向判定"""
    if sma25_30 <= 0:
        return "stop"
    if gmo_price > sma25_30 * up_mult:
        return "buy"
    if gmo_price < sma25_30 * dn_mult:
        return "sell"
    return "stop"

def decide_go_level(
    row: Dict,
    t30: Dict,
    t240: Dict,
    news: Dict,
    vision: Dict,        # {"price": float, "ts": epoch_sec, "ocr_conf": float}
    ref_price: float,    # TVやfeedの直近価格
    gpt_direction: str,
    tv_dir: str,
    atr_30m: Optional[float] = None,
    price_for_atr: Optional[float] = None,
    rr_rule: float = 1.5
) -> Dict:
    """
    STOP/GO/STRONG_GO の3段階判定 + 理由と信頼度を返す。
    前提: weighted_direction, meta_decision, data_quality_gate,
          direction_votes, gmo_bias_direction が利用可能であること。
    戻り: {"level": "STOP|GO|STRONG_GO", "reason": str, "confidence": int}
    """
    # 0) Data Quality Gate
    ok, gate_reason = data_quality_gate(vision, ref_price)
    if not ok:
        return {"level": "STOP", "reason": gate_reason, "confidence": 35}

    # 1) Weighted & Meta
    gmo_price = float(vision["price"])
    weighted_dir, score = weighted_direction(t30, t240, news, gmo_price)
    final_dir, score2, meta_reason = meta_decision(t30, t240, news, gmo_price, gpt_direction)
    score = score2  # metaで最終調整後を採用

    # 2) コンセンサス（votes）
    long_dir = "buy" if float(t240.get("sma25", 0.0)) > float(t240.get("sma75", 0.0)) else "sell"
    gmo_dir  = gmo_bias_direction(gmo_price, float(t30.get("sma25", 0.0)))
    tv_dir   = (tv_dir or "stop").strip().lower()
    if tv_dir not in ("buy", "sell", "stop"):
        tv_dir = "stop"
    maj_dir, votes = direction_votes(long_dir, weighted_dir, gpt_direction, tv_dir, gmo_dir)

    # 3) RRチェック
    def _rr(entry, sl, tp, side):
        # 既存の risk_reward と同等
        if side == "buy":
            risk   = max(entry - sl, 1e-9)
            reward = max(tp - entry, 0.0)
        elif side == "sell":
            risk   = max(sl - entry, 1e-9)
            reward = max(entry - tp, 0.0)
        else:
            return 0.0
        return (reward / risk) if risk > 0 else 0.0

    rr1 = _rr(row["entry"], row["sl"], row["tp1"], final_dir)
    rr2 = _rr(row["entry"], row["sl"], row["tp2"], final_dir)
    rr_ok = max(rr1, rr2) >= rr_rule

    # 4) ボラ適合（任意）
    vola_ok = True
    if atr_30m and price_for_atr:
        vola_ok = (atr_30m / price_for_atr) <= 0.015  # 1.5% 以内

    # 5) レベル判定
    if abs(score) < 0.8:
        return {"level": "STOP", "reason": "score_neutral", "confidence": 45}

    if rr_ok and vola_ok:
        if abs(score) >= 1.5 and votes >= 3:
            level = "STRONG_GO"
        elif votes >= 2:
            level = "GO"
        else:
            level = "STOP"
    else:
        level = "STOP"

    # 6) 信頼度 0-100（簡易合成）
    base = min(95, 60 + int(min(abs(score), 2.5) * 10))   # スコア寄与
    base += (votes - 1) * 5                               # votes寄与
    if not vola_ok:
        base -= 10
    confidence = max(0, min(100, base))

    # 7) 説明文（reason）
    reason = (
        f"meta={final_dir} score={score:.2f} "
        f"votes={votes} ({long_dir}/{weighted_dir}/{gpt_direction}/{tv_dir}/{gmo_dir}); "
        f"RR1={rr1:.2f}, RR2={rr2:.2f}; {meta_reason}"
    )

    return {"level": level, "reason": reason, "confidence": confidence}

# ------------------------------------------------------------
# IFD
# ------------------------------------------------------------

def build_ifd(direction, price, atr):
    if direction == "buy":
        return price, price - atr, price*1.004, price*1.008
    if direction == "sell":
        return price, price + atr, price*0.996, price*0.992
    return price, price, price, price

# ------------------------------------------------------------
# Dawn テーブル（空白行ゼロ）
# ------------------------------------------------------------

def build_dawn_table(rows):
    html = []
    html.append('<table class="dawn-table">')
    html.append(
        "<tr><th>trade_mode</th><th>銘柄</th><th>方向</th>"
        "<th>entry</th><th>SL</th><th>TP1</th><th>TP2</th>"
        "<th>判定</th><th>推奨度</th><th>コメント</th></tr>"
    )

    for r in rows:
        d = r["direction"].upper()
        conf = r["confidence"]
        stars = "★★★★★" if conf>=85 else "★★★★☆" if conf>=70 else \
                "★★★☆☆" if conf>=55 else "★★☆☆☆"

        html.append(
            f"<tr>"
            f"<td>HYBRID</td>"
            f"<td>{r['symbol']}</td>"
            f"<td>{d}</td>"
            f"<td>{r['entry']:.1f}</td>"
            f"<td>{r['sl']:.1f}</td>"
            f"<td>{r['tp1']:.1f}</td>"
            f"<td>{r['tp2']:.1f}</td>"
            f"<td>{d}</td>"
            f"<td>{stars}</td>"
            f"<td>{r['comment']}</td>"
            f"</tr>"
        )

    html.append("</table>")
    return "\n".join(html)

# ------------------------------------------------------------
# Vision 価格抽出（None を完全削除）
# ------------------------------------------------------------

def vision_extract_prices(img_bytes):
    try:
        b64 = base64.b64encode(img_bytes).decode()
        prompt = """
GMOアプリ/PC画面から4銘柄の現在価格(BID or ASK)を読み取り、
以下形式のJSONだけ返してください:

{
 "日本225": 数値,
 "米国NQ100ミニ": 数値,
 "ドイツ40": 数値,
 "金スポット": 数値
}
"""

        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type":"text","text":prompt},
                    {"type":"image_url","image_url":{"url":f"data:image/png;base64,{b64}"}}
                ]
            }],
            temperature=0
        )

        raw = res.choices[0].message.content
        data = json.loads(raw)
        cleaned = {k:v for k,v in data.items() if v is not None}
        return cleaned

    except Exception as e:
        logger.error(f"Vision error: {e}")
        return {}

# ------------------------------------------------------------
# FastAPI
# ------------------------------------------------------------

app = FastAPI(title="CFD3 FIXED")

# CORS設定を強化（credentials不要、全オリジン許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/final", response_class=HTMLResponse)
def ui_final(request: Request):
    """UI用エンドポイント（HTML表示）"""
    try:
        from server.analyze_unified_ifd import analyze_unified_ifd
        result = analyze_unified_ifd()
        return templates.TemplateResponse(
            "result.html",
            {"request":request,
             "results": result.get("dawn_table", ""),
             "market_reports": []}
        )
    except Exception as e:
        logger.error(f"/final error: {e}")
        return HTMLResponse(content=f"<h1>Error</h1><pre>{e}</pre>", status_code=500)

@app.get("/test")
def test_endpoint():
    """テストエンドポイント"""
    return {
        "status": "ok",
        "message": "CFD3 DawnAI is running",
        "version": "200 (FIXED)",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/webhook")
async def webhook_endpoint(request: Request):
    """TradingView Webhook エンドポイント"""
    try:
        data = await request.json()
        logger.info(f"[Webhook] Received: {data}")
        
        symbol = data.get("symbol", "UNKNOWN")
        direction = data.get("direction", "").upper()
        price = float(data.get("price", 0))
        
        return {
            "status": "received",
            "symbol": symbol,
            "direction": direction,
            "price": price,
            "message": f"Alert for {symbol} received",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"[Webhook] Error: {e}")
        return {
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.post("/analyze/image")
async def analyze_image_endpoint(file: UploadFile = File(...)):
    """画像アップロード＋解析エンドポイント"""
    try:
        # ファイルサイズチェック（10MB制限）
        img = await file.read()
        if len(img) > 10 * 1024 * 1024:
            return {"status": "error", "message": "ファイルサイズが10MBを超えています"}
        
        # Vision価格抽出
        prices = vision_extract_prices(img)
        logger.info(f"[Vision] {prices}")

        # IFD解析
        from server.analyze_unified_ifd import analyze_unified_ifd
        result = analyze_unified_ifd(mode="hybrid", gmo_prices=prices)
        result["vision_prices"] = prices
        
        return result
    
    except Exception as e:
        logger.error(f"/analyze/image error: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "results": [],
            "dawn_table": "",
            "day6h_table": ""
        }

# 起動
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("webhook_server:app", host="0.0.0.0", port=8080, reload=True)
