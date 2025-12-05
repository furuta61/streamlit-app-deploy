# -*- coding: utf-8 -*-
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from datetime import datetime
import logging, json

app = FastAPI(title="CFD3 Minimal Webhook Server")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CFD3")

@app.get("/")
def home():
    return HTMLResponse("<h1>✅ CFD3 Webhook Server Running</h1>")

@app.get("/test")
def test():
    return {"status": "ok", "message": "CFD3 Webhook active", "timestamp": datetime.now().isoformat()}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        symbol = data.get("symbol", "UNKNOWN")
        price = data.get("price", 0)
        signal = data.get("signal", "NONE")
        logger.info(f"[Webhook] Received {signal} for {symbol} at {price}")
        return {"status": "ok", "symbol": symbol, "price": price, "signal": signal}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "message": str(e)}
