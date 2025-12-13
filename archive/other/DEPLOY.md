# CFD3 AutoSystem デプロイガイド

## 📋 前提条件

- Docker & Docker Compose インストール済み
- OpenAI API キー取得済み
- ポート 80, 8080, 8501 が利用可能

## 🚀 デプロイ手順

### 1. 環境変数の設定

```bash
# .env ファイルを作成
cp .env.example .env

# エディタで編集
nano .env
```

必須項目:
- `OPENAI_API_KEY`: OpenAI API キー

### 2. Docker デプロイ（推奨）

```bash
# デプロイスクリプト実行
./deploy.sh
```

または手動で:

```bash
# ビルド
docker-compose build

# 起動
docker-compose up -d

# ログ確認
docker-compose logs -f

# 停止
docker-compose down
```

### 3. アクセス確認

- **Streamlit UI**: http://localhost
- **FastAPI Docs**: http://localhost/api/docs
- **Health Check**: http://localhost/health

## 🔧 本番環境デプロイ

### AWS EC2 / VPS の場合

```bash
# サーバーにSSH接続
ssh user@your-server.com

# リポジトリをクローン
git clone https://github.com/your-repo/CFD3_AutoSystem.git
cd CFD3_AutoSystem

# 環境変数を設定
nano .env

# デプロイ
./deploy.sh
```

### ドメイン設定

nginx.conf を編集:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    # SSL証明書がある場合
    # listen 443 ssl;
    # ssl_certificate /etc/nginx/ssl/cert.pem;
    # ssl_certificate_key /etc/nginx/ssl/key.pem;
    
    # ... 残りの設定
}
```

### SSL証明書（Let's Encrypt）

```bash
# Certbot インストール
sudo apt-get install certbot python3-certbot-nginx

# 証明書取得
sudo certbot --nginx -d your-domain.com

# 自動更新設定
sudo certbot renew --dry-run
```

## 📊 監視とメンテナンス

### ログ確認

```bash
# すべてのログ
docker-compose logs -f

# FastAPIのみ
docker-compose logs -f fastapi

# Streamlitのみ
docker-compose logs -f streamlit
```

### ヘルスチェック

```bash
# エンドポイント確認
curl http://localhost/health | jq

# 期待される出力:
# {
#   "status": "ok",
#   "version": "2.1.0",
#   "uptime_sec": 142.5,
#   "server_time": "2025-11-22 14:05:27",
#   "vision_status": "active",
#   "message": "CFD3_AutoSystem v2.1 稼働中 🚀"
# }
```

### コンテナ再起動

```bash
# すべて再起動
docker-compose restart

# FastAPIのみ
docker-compose restart fastapi

# Streamlitのみ
docker-compose restart streamlit
```

### アップデート

```bash
# 最新コードを取得
git pull

# 再ビルド & 再起動
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## 🔒 セキュリティ

### ファイアウォール設定

```bash
# UFW（Ubuntu）
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 環境変数の保護

```bash
# .env ファイルの権限設定
chmod 600 .env
```

### Webhook トークン

`.env` で `WEBHOOK_TOKEN` を設定し、TradingView アラートで同じトークンを使用:

```json
{
  "token": "your-secure-token",
  "symbol": "{{ticker}}",
  "signal": "STRONG_GO"
}
```

## 🐛 トラブルシューティング

### ポート衝突

```bash
# 使用中のポートを確認
lsof -ti:8080
lsof -ti:8501

# プロセスを停止
kill -9 $(lsof -ti:8080)
```

### OpenAI API エラー

```bash
# API キーを確認
grep OPENAI_API_KEY .env

# ヘルスチェックで状態確認
curl http://localhost/health | jq .vision_status
```

### Docker ディスク容量

```bash
# 未使用のイメージ・コンテナを削除
docker system prune -a

# ボリュームも削除
docker system prune -a --volumes
```

## 📈 スケーリング

### 複数インスタンス

docker-compose.yml を編集:

```yaml
services:
  fastapi:
    deploy:
      replicas: 3
```

### ロードバランサー

nginx.conf を編集:

```nginx
upstream fastapi {
    server fastapi1:8080;
    server fastapi2:8080;
    server fastapi3:8080;
}
```

## 📞 サポート

問題が発生した場合:

1. ログを確認: `docker-compose logs -f`
2. ヘルスチェック: `curl http://localhost/health`
3. コンテナ状態: `docker-compose ps`
4. GitHub Issues で報告

---

**CFD3 AutoSystem v2.1.0**  
© 2025 - Automated Trading System
