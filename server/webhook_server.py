# -*- coding: utf-8 -*-
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from openai import OpenAI
import os, json, logging
from collections import deque

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
app = FastAPI(title="CFD3 Webhook Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CFD3")
WEBHOOK_LOGS = deque(maxlen=50)
LATEST_SIGNALS = {}

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("<h1>✅ CFD3 Webhook Server is Running</h1>")

@app.get("/test")
def test():
    return {"status": "ok","message": "CFD3 Webhook active","timestamp": datetime.now().isoformat()}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        symbol = data.get("symbol", "UNKNOWN")
        direction = data.get("direction", "NONE").upper()
        signal = data.get("signal", "NONE")
        price = float(data.get("price", 0))
        news = data.get("news", "")
        logger.info(f"[Webhook] Received signal {signal} for {symbol}")
        WEBHOOK_LOGS.append(f"{datetime.now().isoformat()} | {symbol} | {signal} | {price}")

        prompt = f"""
銘柄: {symbol}
シグナル: {signal}
方向: {direction}
現在価格: {price}
ニュース: {news}

この情報から IFD 注文（entry, tp1, sl, comment）を提案してください。
出力は JSON のみ:
{{"entry": 数値, "tp1": 数値, "sl": 数値, "comment": "短い日本語コメント"}}
"""
        plan = {"entry": price, "tp1": price*1.01, "sl": price*0.99, "comment": "default"}
        try:
            ai = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200  # ✅ top_p削除済み
            )
            content = ai.choices[0].message.content.strip()
            logger.info(f"[AI] Raw: {content}")
            plan = json.loads(content)
        except Exception as e:
            logger.error(f"[AI Error] {e}")
        logger.info(f"[AI] Generated IFD → Entry: {plan['entry']} / TP1: {plan['tp1']} / SL: {plan['sl']}")
        return {"status": "ok", "symbol": symbol, "plan": plan}
    except Exception as e:
        logger.error(f"[Webhook Error] {e}")
        return {"status": "error", "message": str(e)}

@app.get("/logs", response_class=HTMLResponse)
def logs():
    logs_html = "<br>".join(reversed(WEBHOOK_LOGS))
    return HTMLResponse(f"<pre>{logs_html}</pre>")
