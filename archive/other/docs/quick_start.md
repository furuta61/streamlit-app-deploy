## 🚀 Quick Start（TradingView Webhook パイプライン）

このプロジェクトでは、**TradingView のアラートをローカルの Python サーバーで受信し、  
マーケットデータ処理パイプラインに統合**する仕組みを提供します。

### 🧩 構成概要

データフローや全体構成については  
📘 [`docs/pipeline_overview.md`](pipeline_overview.md) を参照してください。

---

### 🧰 起動手順

#### 1️⃣ 仮想環境を有効化

```bash
source .venv/bin/activate
```

#### 2️⃣ Webhook サーバーを起動

```bash
python receiver.py
```

サーバーは http://127.0.0.1:8000 で待ち受けます。

#### 3️⃣ ngrok で外部公開

別のターミナルで以下を実行します：

```bash
ngrok http 8000
```

実行結果に出る「Forwarding」URL をコピー（例: https://xxxx.ngrok-free.dev）

TradingView の Webhook URL に以下のように設定します：

```text
https://xxxx.ngrok-free.dev/webhook
```

#### 4️⃣ TradingView アラート設定例

Webhook メッセージ欄に次を設定：

```json
{"source":"tradingview","symbol":"JP225","price":{{close}},"time":"{{timenow}}"}
```

これにより、TradingView のシグナルがローカルに自動送信されます。

#### 5️⃣ ログ確認

受信したデータは output/tradingview.jsonl に追記されます。

```bash
tail -n 5 output/tradingview.jsonl
```

出力例：

```json
{"timestamp": "2025-11-06T00:22:03.053494", "data": {"source": "tradingview", "symbol": "JP225", "price": 51021.5, "time": "2025-11-06T00:12:35Z"}}
```

#### 6️⃣ データ統合（ensemble実行）

TradingView データが正しく取り込まれているか確認：

```bash
python market_data_ensemble.py JP225
```

ログに 'source': 'tradingview' が含まれていればOKです。

🔐 オプション：トークン認証（セキュリティ強化）

receiver.py にトークン検証を追加し、URLを以下のようにします：

```text
https://xxxx.ngrok-free.dev/webhook?token=YOUR_SECRET
```

環境変数 `TV_WEBHOOK_SECRET` にトークンを設定し、TradingView 側でも同じトークンを URL に付与します。

重要（運用者向け）：TV_WEBHOOK_SECRET の設定と利用例

運用で忘れがちなポイントをまとめます。必ず本番環境ではトークンを設定してください。

- 環境変数の設定例（macOS / Linux）:

```bash
export TV_WEBHOOK_SECRET="mysecret123"
```

- TradingView では URL にクエリで付与する方法が簡単です：

```
https://xxxx.ngrok-free.dev/webhook?token=mysecret123
```

- あるいはヘッダ方式（より安全）を利用できます（TradingView がヘッダ送信をサポートしている場合や、自前のテストツールで利用する場合）：

```
X-TV-Token: mysecret123
```

- テスト curl（クエリ方式・ヘッダ方式両方の例）:

```bash
# クエリ方式
curl -X POST -H "Content-Type: application/json" \
	-d '{"source":"tradingview","symbol":"JP225","price":51200,"time":"now"}' \
	'http://127.0.0.1:8000/webhook?token=mysecret123'

# ヘッダ方式
curl -X POST -H "Content-Type: application/json" \
	-H "X-TV-Token: mysecret123" \
	-d '{"source":"tradingview","symbol":"JP225","price":51200,"time":"now"}' \
	http://127.0.0.1:8000/webhook
```

運用ヒント: `TV_WEBHOOK_SECRET` が未設定だと検証はスキップされます（開発時は便利ですが、本番では必ず設定してください）。

🧠 補足情報

ngrok ログ確認： http://127.0.0.1:4040

Webhook テスト送信：

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{"source":"tradingview","symbol":"JP225","price":12345,"time":"now"}' \
http://127.0.0.1:8000/webhook
```

プロセス停止： Ctrl + C

© 2025 OTOMI CFD3_AutoSystem
