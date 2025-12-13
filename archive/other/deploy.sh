#!/bin/bash
# CFD3 AutoSystem デプロイスクリプト

set -e

echo "🚀 CFD3 AutoSystem デプロイ開始"

# 環境変数チェック
if [ ! -f .env ]; then
    echo "❌ .env ファイルが見つかりません"
    echo "📝 .env.example を参考に .env を作成してください"
    exit 1
fi

# Docker がインストールされているか確認
if ! command -v docker &> /dev/null; then
    echo "❌ Docker がインストールされていません"
    echo "📦 https://docs.docker.com/get-docker/ を参照してください"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose がインストールされていません"
    echo "📦 https://docs.docker.com/compose/install/ を参照してください"
    exit 1
fi

# 古いコンテナを停止
echo "🛑 既存のコンテナを停止中..."
docker-compose down || true

# イメージをビルド
echo "🔨 Dockerイメージをビルド中..."
docker-compose build --no-cache

# コンテナを起動
echo "▶️  コンテナを起動中..."
docker-compose up -d

# ヘルスチェック
echo "🔍 ヘルスチェック中..."
sleep 10

if curl -f http://localhost/health &> /dev/null; then
    echo "✅ デプロイ成功！"
    echo ""
    echo "📊 アクセス情報:"
    echo "  - Streamlit UI: http://localhost"
    echo "  - FastAPI Docs: http://localhost/api/docs"
    echo "  - Health Check: http://localhost/health"
    echo ""
    echo "📝 ログ確認: docker-compose logs -f"
    echo "🛑 停止: docker-compose down"
else
    echo "❌ ヘルスチェック失敗"
    echo "📋 ログを確認してください: docker-compose logs"
    exit 1
fi
