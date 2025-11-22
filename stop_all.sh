#!/usr/bin/env bash
# システム停止スクリプト
# 使い方: ./stop_all.sh

set -euo pipefail

echo "=========================================="
echo "  CFD3_AutoSystem 停止中"
echo "=========================================="
echo ""

# 1. Cloudflare Tunnel 停止
echo "[1/2] Cloudflare Tunnel 停止中..."
pkill -f cloudflared 2>/dev/null && echo "  ✅ Tunnel 停止完了" || echo "  ℹ️ Tunnel は起動していません"

# 2. FastAPI 停止
echo ""
echo "[2/2] FastAPI 停止中..."
lsof -ti:8080 | xargs kill -9 2>/dev/null && echo "  ✅ FastAPI 停止完了" || echo "  ℹ️ FastAPI は起動していません"

echo ""
echo "✅ 全サービス停止完了"
