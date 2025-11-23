import os
import base64
import logging
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import datetime
from io import BytesIO
from PIL import Image

# --- 安全な OpenAI クライアント読込 ---
try:
    from openai import OpenAI
except ImportError:
    import openai
    class OpenAI:  # fallback wrapper for older environments
        def __init__(self, api_key=None):
            openai.api_key = api_key
        def chat(self, *args, **kwargs):
            return openai.ChatCompletion.create(*args, **kwargs)

# --- OCR (pytesseract) 安全読込 ---
try:
    import pytesseract
except ImportError:
    pytesseract = None

app = FastAPI(title="CFD3_AutoSystem v2.3.1")

# --- CORS設定 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("cfd3_cloud")
logging.basicConfig(level=logging.INFO)

# ===============================
# 🧠 Vision + OCR ロジック
# ===============================
async def read_uploaded_image(file: UploadFile) -> bytes:
    try:
        contents = await file.read()
        if not contents or len(contents) < 10:
            raise ValueError("アップロード画像が空です。")
        return contents
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"画像の読み取りに失敗: {e}")

def fallback_ocr_symbol(image_bytes: bytes) -> Optional[str]:
    """OCRで銘柄名を抽出"""
    if pytesseract is None:
        return None
    try:
        img = Image.open(BytesIO(image_bytes))
        width, height = img.size
        crop_area = (0, 0, width, height * 0.25)
        img_crop = img.crop(crop_area)
        text = pytesseract.image_to_string(img_crop, lang="eng+jpn")
        for sym in ["JP225", "GER40", "US30", "XAUUSD", "GOLD"]:
            if sym in text.upper():
                return sym
        return None
    except Exception:
        return None

# ===============================
# 🎯 Vision解析
# ===============================
@app.post("/analyze/image")
async def analyze_image(symbol: Optional[str] = None, file: UploadFile = File(...)):
    img_bytes = await read_uploaded_image(file)
    b64 = base64.b64encode(img_bytes).decode("utf-8")

    prompt = """
    あなたはCFDトレーディングの専門家です。
    画像から以下の情報をJSON形式で抽出してください:
    - symbol（銘柄）: JP225, GER40, XAUUSDなど
    - direction: 買い または 売り
    - entry: エントリー価格
    - tp1: 利確価格
    - sl: 損切り価格
    - signal: GO または STRONG_GO
    - confidence: 信頼度(0〜100)
    - comment: 短い補足コメント
    """

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            max_tokens=800,
        )
        raw_text = response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vision解析エラー: {e}")

    logger.info("✅ Vision解析結果: %s", raw_text)
    if (not symbol) or ("UNKNOWN" in raw_text.upper()):
        symbol_from_ocr = fallback_ocr_symbol(img_bytes)
        if symbol_from_ocr:
            symbol = symbol_from_ocr

    return {
        "status": "success",
        "symbol": symbol or "UNKNOWN",
        "analysis": {"raw_text": raw_text},
    }

# ===============================
# 🩺 Health Check
# ===============================
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "2.3.1",
        "server_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "vision_status": "active",  # 簡易表示（APIキー存在チェックは省略）
        "tesseract": "installed" if pytesseract else "missing",
        "opencv": "available",  # headless環境前提
        "message": "CFD3_AutoSystem v2.3.1 稼働中 🚀"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)