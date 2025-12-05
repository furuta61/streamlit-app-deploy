# -*- coding: utf-8 -*-
from fastapi import FastAPI, Request
from datetime import datetime
import json, logging

app = FastAPI(title="CFD3 Webhook Server")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CFD3")

@app.get("/")
def home():
    return {"status": "ok", "message": "CFD3 Server Root"}

@app.get("/test")
def test():
    return {"status": "ok", "message": "CFD3 Webhook active", "timestamp": datetime.now().isoformat()}

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    symbol = data.get("symbol", "UNKNOWN")
    signal = data.get("signal", "NONE")
    price = data.get("price", 0)
    logger.info(f"[Webhook] Received {signal} for {symbol} at {price}")
    return {"status": "ok", "symbol": symbol, "signal": signal, "price": price}
