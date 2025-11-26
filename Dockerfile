# === ベースイメージ ===
FROM python:3.11-slim

# === システム依存パッケージ ===
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-jpn \
    libgl1 \
    libglib2.0-0 \
    gcc \
    g++ \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# === 作業ディレクトリ ===
WORKDIR /app

# === 依存関係をインストール ===
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# === ソースコードをコピー ===
COPY . .

# === 起動コマンド ===
CMD ["sh", "-c", "cd server && uvicorn webhook_server:app --host 0.0.0.0 --port ${PORT:-8080}"]
