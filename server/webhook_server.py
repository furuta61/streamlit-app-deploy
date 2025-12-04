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

# Webhook受信ログ & 銘柄別状態管理
WEBHOOK_LOGS = []
LATEST_SIGNALS = {}  # 銘柄別の最新状態を保持

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
        symbol = data.get("symbol", "UNKNOWN")
        direction = data.get("direction", "").upper()
        price = float(data.get("price", 0))
        time_str = data.get("time", "")
        
        # ログエントリ作成
        log_entry = f"[Webhook] {time_str} - {symbol} ({direction}) @ {price}"
        WEBHOOK_LOGS.insert(0, log_entry)
        if len(WEBHOOK_LOGS) > 50:
            WEBHOOK_LOGS.pop()
        
        # 最新シグナル情報更新
        LATEST_SIGNALS[symbol] = {
            "symbol": symbol,
            "signal": direction,
            "price": price,
            "time": time_str,
            "updated": datetime.now().strftime("%H:%M:%S")
        }
        
        logger.info(f"[Webhook] Received: {symbol} {direction} @ {price}")
        
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

@app.get("/test", response_class=HTMLResponse)
async def test_ui_page():
    """Webhook受信確認UI（銘柄別最新ステータス＋履歴）"""
    
    # テーブルボディ生成
    table_body = ""
    if LATEST_SIGNALS:
        for sym in sorted(LATEST_SIGNALS.keys()):
            info = LATEST_SIGNALS[sym]
            signal = info['signal']
            # Signal に応じて色分け
            if signal == "STRONG_GO":
                signal_class = "signal-strong"
            elif signal == "GO":
                signal_class = "signal-go"
            else:
                signal_class = "signal-wait"
            
            table_body += f"""
            <tr>
                <td><strong>{sym}</strong></td>
                <td class="{signal_class}">{signal}</td>
                <td>{info['price']}</td>
                <td class="timestamp">{info['time']}</td>
                <td class="timestamp">{info['updated']}</td>
            </tr>
            """
    else:
        table_body = "<tr><td colspan='5' style='color: #666;'>データなし - TradingView からアラートを送信してください</td></tr>"
    
    # ログボディ生成
    log_body = ""
    if WEBHOOK_LOGS:
        for line in WEBHOOK_LOGS[:30]:
            if "Error" in line:
                log_body += f'<div class="log error">{line}</div>\n'
            else:
                log_body += f'<div class="log">{line}</div>\n'
    else:
        log_body = '<div class="log" style="color: #666; text-align: center;">待機中...</div>\n'
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>CFD3 Webhook Monitor</title>
        <meta http-equiv="refresh" content="5">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #0d1117;
                color: #e6edf3;
                padding: 20px;
                min-height: 100vh;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            h1 {{
                color: #58a6ff;
                margin-bottom: 8px;
                font-size: 28px;
            }}
            p {{
                color: #8b949e;
                margin-bottom: 20px;
            }}
            hr {{
                border: none;
                border-top: 1px solid #30363d;
                margin: 20px 0;
            }}
            h2 {{
                color: #79c0ff;
                font-size: 16px;
                margin: 30px 0 15px 0;
                text-transform: uppercase;
                letter-spacing: 1px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                overflow: hidden;
            }}
            th {{
                background-color: #161b22;
                color: #58a6ff;
                padding: 12px;
                text-align: left;
                font-weight: 600;
                border-bottom: 2px solid #30363d;
            }}
            td {{
                padding: 12px;
                border-bottom: 1px solid #21262d;
            }}
            tr:last-child td {{
                border-bottom: none;
            }}
            tr:hover {{
                background-color: #161b22;
            }}
            .timestamp {{
                color: #8b949e;
                font-size: 12px;
            }}
            .signal-strong {{
                color: #00ff99;
                font-weight: bold;
                background: rgba(0, 255, 153, 0.1);
                padding: 4px 8px;
                border-radius: 4px;
            }}
            .signal-go {{
                color: #58a6ff;
                font-weight: bold;
                background: rgba(88, 166, 255, 0.1);
                padding: 4px 8px;
                border-radius: 4px;
            }}
            .signal-wait {{
                color: #ffcc00;
                font-weight: bold;
                background: rgba(255, 204, 0, 0.1);
                padding: 4px 8px;
                border-radius: 4px;
            }}
            .logs-container {{
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 15px;
                max-height: 500px;
                overflow-y: auto;
            }}
            .log {{
                padding: 8px;
                margin: 4px 0;
                font-family: 'Courier New', monospace;
                font-size: 12px;
                color: #8b949e;
                border-left: 3px solid #30363d;
                padding-left: 12px;
            }}
            .log.error {{
                color: #f85149;
                border-left-color: #f85149;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #30363d;
                font-size: 12px;
                color: #8b949e;
                text-align: center;
            }}
            .status-badge {{
                display: inline-block;
                padding: 4px 8px;
                background: #1f6feb;
                border-radius: 20px;
                font-size: 12px;
                color: #fff;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 CFD3 Webhook Monitor</h1>
            <p>TradingView リアルタイム受信状態（5秒ごと自動更新）</p>
            <hr>
            
            <h2>📊 最新シグナル一覧</h2>
            <table>
                <thead>
                    <tr>
                        <th>銘柄</th>
                        <th>Signal</th>
                        <th>価格</th>
                        <th>受信時刻</th>
                        <th>更新</th>
                    </tr>
                </thead>
                <tbody>
                    {table_body}
                </tbody>
            </table>
            
            <h2>🕓 受信履歴（最新30件）</h2>
            <div class="logs-container">
                {log_body}
            </div>
            
            <div class="footer">
                <p><span class="status-badge">🟢 RUNNING</span></p>
                <p>CFD3 DawnAI v200 | TradingView Webhook Monitor</p>
                <p>最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S JST')}</p>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

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

@app.get("/ifd", response_class=HTMLResponse)
async def ifd_generate():
    """
    AIによるIFD生成（Webhook信号ベース）
    最新の受信シグナルをもとにAI判定・IFD表を生成
    """
    if not LATEST_SIGNALS:
        return HTMLResponse("""
        <html>
        <head>
            <meta charset="utf-8">
            <title>AI IFD Generator</title>
            <style>
                body { font-family: 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; padding: 20px; }
                .container { max-width: 900px; margin: 0 auto; }
                h2 { color: #f85149; }
                a { color: #58a6ff; text-decoration: none; }
            </style>
        </head>
        <body>
            <div class="container">
                <h2>🚫 データなし</h2>
                <p>Webhook信号を受信してから再実行してください。</p>
                <p><a href='/test'>← Webhook Monitor に戻る</a></p>
            </div>
        </body>
        </html>
        """)

    # IFD データ生成
    ifd_rows = []
    for sym, info in LATEST_SIGNALS.items():
        signal = info['signal']
        price = float(info['price'])
        
        # ATR相当（簡易）
        atr = price * 0.002
        
        # 方向を Signal から判定
        if signal in ["BUY", "GO", "STRONG_GO"]:
            direction = "BUY"
            direction_class = "buy"
            entry = price
            sl = price - atr
            tp1 = price + atr * 2
            tp2 = price + atr * 4
        else:
            direction = "SELL"
            direction_class = "sell"
            entry = price
            sl = price + atr
            tp1 = price - atr * 2
            tp2 = price - atr * 4
        
        # 推奨度（Signal に基づく）
        if signal == "STRONG_GO":
            stars = "★★★★★"
            judgment = "強気"
        elif signal == "GO":
            stars = "★★★★☆"
            judgment = "買い"
        else:
            stars = "★★★☆☆"
            judgment = "保留"
        
        ifd_rows.append({
            "symbol": sym,
            "direction": direction,
            "direction_class": direction_class,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "stars": stars,
            "judgment": judgment,
            "signal": signal
        })
    
    # テーブルHTML生成
    table_html = ""
    for row in ifd_rows:
        table_html += f"""
        <tr>
            <td><strong>{row['symbol']}</strong></td>
            <td class="{row['direction_class']}">{row['direction']}</td>
            <td>{row['entry']:.2f}</td>
            <td>{row['sl']:.2f}</td>
            <td>{row['tp1']:.2f}</td>
            <td>{row['tp2']:.2f}</td>
            <td class="star">{row['stars']}</td>
            <td>{row['judgment']}</td>
            <td><span class="badge">{row['signal']}</span></td>
        </tr>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>AI IFD Generator</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #0d1117;
                color: #e6edf3;
                padding: 20px;
                min-height: 100vh;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            h1 {{
                color: #58a6ff;
                margin-bottom: 8px;
                font-size: 28px;
            }}
            p {{
                color: #8b949e;
                margin-bottom: 20px;
            }}
            hr {{
                border: none;
                border-top: 1px solid #30363d;
                margin: 20px 0;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                overflow: hidden;
            }}
            th {{
                background-color: #161b22;
                color: #58a6ff;
                padding: 12px;
                text-align: left;
                font-weight: 600;
                border-bottom: 2px solid #30363d;
            }}
            td {{
                padding: 12px;
                border-bottom: 1px solid #21262d;
                font-size: 14px;
            }}
            tr:last-child td {{
                border-bottom: none;
            }}
            tr:hover {{
                background-color: #161b22;
            }}
            .buy {{
                color: #00ff99;
                font-weight: bold;
            }}
            .sell {{
                color: #f85149;
                font-weight: bold;
            }}
            .stop {{
                color: #ffcc00;
                font-weight: bold;
            }}
            .star {{
                color: #ffd700;
                font-weight: bold;
                font-size: 16px;
            }}
            .badge {{
                display: inline-block;
                padding: 4px 8px;
                background: #1f6feb;
                border-radius: 12px;
                font-size: 11px;
                color: #fff;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #30363d;
                font-size: 12px;
                color: #8b949e;
                text-align: center;
            }}
            a {{
                color: #58a6ff;
                text-decoration: none;
                margin: 0 10px;
            }}
            a:hover {{
                text-decoration: underline;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 AI IFD Generator</h1>
            <p>最新のWebhook信号をもとにAI判定・IFD生成を行いました。</p>
            <hr>
            
            <table>
                <thead>
                    <tr>
                        <th>銘柄</th>
                        <th>方向</th>
                        <th>Entry</th>
                        <th>SL</th>
                        <th>TP1</th>
                        <th>TP2</th>
                        <th>推奨度</th>
                        <th>判定</th>
                        <th>Signal</th>
                    </tr>
                </thead>
                <tbody>
                    {table_html}
                </tbody>
            </table>
            
            <div class="footer">
                <p>生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S JST')}</p>
                <p>
                    <a href='/test'>← Webhook Monitor</a>
                    <a href='/ifd'>🔄 再生成</a>
                </p>
                <p>CFD3 DawnAI v200 | AI IFD Generator</p>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# 起動
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("webhook_server:app", host="0.0.0.0", port=8080, reload=True)
