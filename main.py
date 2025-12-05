# main.py
from fastapi import FastAPI, Request
from datetime import datetime
import logging

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CFD3")

@app.get("/")
def root():
    return {"status": "ok", "message": "Root endpoint active"}

@app.get("/test")
def test():
    return {"status": "ok", "message": "CFD3 Clean version", "timestamp": datetime.now().isoformat()}

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    symbol = data.get("symbol", "UNKNOWN")
    price = data.get("price", 0)
    signal = data.get("signal", "NONE")
    logger.info(f"[Webhook] Received {signal} for {symbol} at {price}")
    return {"status": "ok", "symbol": symbol, "signal": signal, "price": price}

