# CFD3_AutoSystem

This repository contains tools for ingesting market data and a local webhook pipeline to receive TradingView alerts and integrate them into an ensemble data pipeline.

Quick pointers

- Quick Start: `docs/quick_start.md`
- Pipeline overview: `docs/pipeline_overview.md`
- TradingView webhook details: `docs/TV_WEBHOOK.md`

Important: TV_WEBHOOK_SECRET

For production use, set the environment variable `TV_WEBHOOK_SECRET` to a secret token and include it in your TradingView Webhook URL as `?token=YOUR_SECRET` or send it via the `X-TV-Token` HTTP header. If this environment variable is not set, `receiver.py` will skip token validation (useful for development but insecure for production).

Example:

```bash
export TV_WEBHOOK_SECRET=mysecret123
```

Then use either:

```
https://<ngrok-forwarding>/webhook?token=mysecret123
```

or set the header `X-TV-Token: mysecret123` when posting to `/webhook`.

---

© 2025 OTOMI CFD3_AutoSystem

---

## 公開 (デプロイ) 手順まとめ

ここでは FastAPI (画像解析 API) と Streamlit UI を公開する最短ステップを示します。

### 1. 必須環境変数

`.env` などに以下を設定してください:

```
OPENAI_API_KEY=sk-xxxx...
PUBLIC_BASE_URL=https://<あなたのFastAPI公開URL>
```

`PUBLIC_BASE_URL` を設定すると `webhook_mail/streamlit_app.py` が自動的に `API_URL=<PUBLIC_BASE_URL>/analyze/image` を使用します。未設定の場合はローカル `http://localhost:8080` を参照します。

### 2. FastAPI 起動 (ローカル開発)

```
source .venv/bin/activate
python -m uvicorn webhook_mail.main:app --host 0.0.0.0 --port 8080
```

ヘルスチェック:

```
curl http://localhost:8080/health
```

### 3. Cloudflare Tunnel で一時公開 (簡易)

```
cloudflared tunnel --url http://localhost:8080
```

表示された `https://xxxxx.trycloudflare.com` を `PUBLIC_BASE_URL` に設定し Streamlit を再起動/再デプロイします。

### 4. Streamlit (ローカル)

```
source .venv/bin/activate
streamlit run webhook_mail/streamlit_app.py
```

### 5. Streamlit Cloud での上書きデプロイ

1. 変更を GitHub に push
2. Streamlit Cloud の Secrets に以下を追加
	```
	OPENAI_API_KEY=sk-xxxx
	PUBLIC_BASE_URL=https://xxxxx.trycloudflare.com
	```
3. アプリを Rerun (自動/手動)

### 6. 動作確認チェックリスト

- `API_URL = ...` が画面冒頭に表示される
- スクリーンショットアップロード → 解析成功
- 日本語IFDテーブル表示
- `curl https://xxxxx.trycloudflare.com/health` が `status: ok`

### 7. 本番向け (推奨)

Cloudflare Tunnel の代わりに VPS / EC2 上で常時稼働し Nginx リバースプロキシ・HTTPS を付与してください。`systemd` サービス例は `DEPLOY.md` を参照予定 (未整備なら追記可能)。

### 8. 代表的トラブルシュート

| 症状 | 原因 | 対処 |
|------|------|------|
| Streamlit で 500 | FastAPI が落ちている | FastAPI プロセス再起動 / ログ確認 |
| Vision が空結果 | 画像前処理失敗 / モデル限界 | もう一度アップロード, 画質改善, グレースケール再試行ログ確認 |
| `vision_status: error:405` | `/v1/models` POST の仕様 | 正常。無視して OK |
| `tunnel_status: unreachable` | トンネルURL自己参照 | 外部から一度アクセスして再確認 |

### 9. 安全運用メモ

- APIキーは必ず Secrets / .env で管理し Git に含めない
- ログに価格や注文情報が残るため、公開環境ではローテーション設定推奨
- 過負荷を避けるため画像解析のリクエスト頻度を制御

---

## コミット & デプロイ最速コマンド

```
git add webhook_mail/streamlit_app.py README.md
git commit -m "docs: 公開手順とAPI_URL動的化追加"
git push origin master
```

---

## .env.example (抜粋)

```
OPENAI_API_KEY=sk-xxxx
PUBLIC_BASE_URL=https://xxxxx.trycloudflare.com
TV_WEBHOOK_SECRET=your_tv_secret
DATA_DIR=./data
IFD_RUN_MODE=closed_60m
```

