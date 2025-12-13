#!/usr/bin/env bash
# Cloudflare Tunnel 自動再接続スクリプト
# FastAPI (port 8080) を公開し、切断時に自動で再接続します。

set -euo pipefail

PORT=8080
LOG_FILE="logs/cloudflare_tunnel.log"
RESTART_DELAY=5

# ログディレクトリ作成
mkdir -p logs

echo "=== Cloudflare Tunnel 自動再接続モード ===" | tee -a "$LOG_FILE"
echo "FastAPI port: $PORT" | tee -a "$LOG_FILE"
echo "ログ: $LOG_FILE" | tee -a "$LOG_FILE"
echo "停止: Ctrl+C" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

while true; do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] トンネル起動中..." | tee -a "$LOG_FILE"
  
  # cloudflared 実行（切断されるまでブロック）
  cloudflared tunnel --url http://localhost:$PORT 2>&1 | tee -a "$LOG_FILE" || {
    EXIT_CODE=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ トンネル切断 (exit code: $EXIT_CODE)" | tee -a "$LOG_FILE"
  }
  
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${RESTART_DELAY}秒後に再接続..." | tee -a "$LOG_FILE"
  sleep "$RESTART_DELAY"
done
