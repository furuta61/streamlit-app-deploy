# main.py
from fastapi import FastAPI, Request
from datetime import datetime

app = FastAPI()

@app.get("/test")
def test():
    return {
        "status": "ok",
        "message": "CFD3 Clean version",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    symbol = data.get("symbol")
    signal = data.get("signal")
    price = data.get("price")
    print(f"[Webhook] Received {signal} for {symbol} at {price}")
    return {"status": "ok", "symbol": symbol, "signal": signal, "price": price}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000)

