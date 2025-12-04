# -*- coding: utf-8 -*-
"""
Dawn IFD Trader - Backend API
FastAPI ベースのシンプルなIFD判定API
"""

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from models.ifd_engine import analyze_entry

app = FastAPI(
    title="Dawn IFD Trader API",
    version="2025.12.03",
    description="GMOハイブリッドIFD計算エンジン"
)

# CORS設定（フロントエンド連携用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番では具体的なドメインを指定
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def root():
    """APIルート - 簡易ダッシュボード"""
    return """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <title>Dawn IFD Trader API</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .container {
                background: rgba(255,255,255,0.1);
                border-radius: 15px;
                padding: 30px;
                backdrop-filter: blur(10px);
            }
            h1 { margin-top: 0; }
            .endpoint {
                background: rgba(255,255,255,0.2);
                padding: 15px;
                margin: 10px 0;
                border-radius: 8px;
            }
            code {
                background: rgba(0,0,0,0.3);
                padding: 2px 8px;
                border-radius: 4px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Dawn IFD Trader API</h1>
            <p>GMOハイブリッドIFD計算エンジン - Version 2025.12.03</p>
            
            <h2>📡 利用可能なエンドポイント</h2>
            
            <div class="endpoint">
                <strong>POST /analyze</strong><br>
                CSV形式のOHLCデータから IFD を判定<br>
                <code>curl -X POST -F "csv_file=@data.csv" -F "symbol=JP225" http://localhost:8000/analyze</code>
            </div>
            
            <div class="endpoint">
                <strong>GET /health</strong><br>
                APIヘルスチェック<br>
                <code>curl http://localhost:8000/health</code>
            </div>
            
            <div class="endpoint">
                <strong>GET /docs</strong><br>
                Swagger UI 対話的ドキュメント
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/health")
async def health_check():
    """ヘルスチェック"""
    return {"status": "healthy", "service": "Dawn IFD Trader", "version": "2025.12.03"}


@app.post("/analyze")
async def analyze(
    csv_file: UploadFile = File(..., description="OHLC CSV file (time,open,high,low,close,volume)"),
    symbol: str = Form("JP225", description="Symbol code: JP225, NAS100, GER40, XAUUSD"),
    timeframe: str = Form("30m", description="Timeframe: 30m, 1h, 4h"),
    sentiment_pos: float = Form(50, description="Positive sentiment % (0-100)"),
    sentiment_neg: float = Form(20, description="Negative sentiment % (0-100)")
):
    """
    CSV形式のOHLCデータからIFDを判定
    
    - **csv_file**: OHLC CSV (time,open,high,low,close,volume)
    - **symbol**: 銘柄コード (JP225, NAS100, GER40, XAUUSD)
    - **timeframe**: 時間足
    - **sentiment_pos/neg**: ニュース感情スコア（オプション）
    """
    try:
        # CSVを読み込み
        content = await csv_file.read()
        df = pd.read_csv(io.BytesIO(content))
        
        # カラム検証
        required_columns = ["time", "open", "high", "low", "close", "volume"]
        if not all(col in df.columns for col in required_columns):
            raise HTTPException(
                status_code=400,
                detail=f"CSV must contain columns: {required_columns}"
            )
        
        # 感情データ
        sentiment = {
            "positive": sentiment_pos,
            "negative": sentiment_neg,
            "neutral": 100 - sentiment_pos - sentiment_neg
        }
        
        # IFD計算
        result = analyze_entry(symbol, df, timeframe, sentiment)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return JSONResponse(content=result)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/symbols")
async def list_symbols():
    """対応銘柄一覧"""
    from models.ifd_engine import GMO_PRICES, TICK_SIZES
    
    symbols = []
    for sym in GMO_PRICES.keys():
        symbols.append({
            "symbol": sym,
            "bid": GMO_PRICES[sym]["bid"],
            "ask": GMO_PRICES[sym]["ask"],
            "tick_size": TICK_SIZES[sym]
        })
    
    return {"symbols": symbols}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
