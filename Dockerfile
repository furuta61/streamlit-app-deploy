# ---- Base ----
FROM python:3.11-slim

# ---- System Dependencies ----
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-jpn \
    libgl1 \
    libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# ---- Working Directory ----
WORKDIR /app

# ---- Copy Files ----
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY . .

# ---- Expose Port ----
ENV PORT=8080
EXPOSE 8080

# ---- Run App ----
WORKDIR /app/server
CMD ["uvicorn", "webhook_server:app", "--host", "0.0.0.0", "--port", "8080"]
