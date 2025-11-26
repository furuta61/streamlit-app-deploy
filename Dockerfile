# CFD3 AutoSystem Dockerfile
FROM python:3.11-slim

# 作業ディレクトリ
WORKDIR /app

# システムパッケージのインストール
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-jpn \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Python依存関係のインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# 環境変数
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# FastAPI起動
CMD ["sh", "-c", "cd server && uvicorn webhook_server:app --host 0.0.0.0 --port ${PORT:-8080}"]
