#!/usr/bin/env bash
# 完全自動起動スクリプト（FastAPI + Tunnel）
# 使い方: ./start_all.sh

set -euo pipefail

PROJECT_DIR="/Users/otomi/Desktop/vs code/CFD3_AutoSystem"
cd "$PROJECT_DIR"

echo "=========================================="
echo "  CFD3_AutoSystem 完全自動起動"
echo "=========================================="
echo ""

# 1. FastAPI 起動確認
echo "[1/3] FastAPI 起動確認 (port 8080)..."
if lsof -ti:8080 > /dev/null 2>&1; then
  echo "  ✅ FastAPI は既に起動済み (PID: $(lsof -ti:8080))"
else
  echo "  ⚠️ FastAPI が起動していません。起動中..."
  source .venv/bin/activate
  nohup python -m uvicorn webhook_mail.main:app --host 0.0.0.0 --port 8080 > logs/fastapi.log 2>&1 &
  FASTAPI_PID=$!
  echo "  ✅ FastAPI 起動完了 (PID: $FASTAPI_PID)"
  sleep 3
fi

# 2. Cloudflare Tunnel 起動
echo ""
echo "[2/3] Cloudflare Tunnel 起動中..."
echo "  ログ: logs/cloudflare_tunnel.log"
echo "  停止: Ctrl+C または pkill -f cloudflared"
echo ""

./start_tunnel.sh &
TUNNEL_PID=$!

echo ""
echo "[3/3] 起動完了"
echo "  FastAPI: http://localhost:8080"
echo "  Tunnel PID: $TUNNEL_PID"
echo ""
echo "📋 公開URLは約5秒後に表示されます（logs/cloudflare_tunnel.log を確認）"
echo ""
echo "停止方法:"
echo "  pkill -f cloudflared    # Tunnel停止"
echo "  lsof -ti:8080 | xargs kill -9  # FastAPI停止"
echo ""

# ログをリアルタイム表示
tail -f logs/cloudflare_tunnel.log
