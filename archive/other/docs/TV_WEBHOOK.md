# TradingView Webhook 設定マニュアル

このドキュメントは `receiver.py`（`/webhook`）へ送信する TradingView のアラート設定方法、ngrok による公開手順、トークン認証の付与方法、テスト例をまとめた実践マニュアルです。

---

## 目次
- 概要
- ngrok でローカルを公開する
- TradingView 側のアラート設定（Pine/Alert JSON）
- セキュリティ：トークン認証の追加方法
- テスト手順とトラブルシュート

---

## 概要

- 送信先: `https://<YOUR_NGROK_FORWARDING>/webhook`（ngrok が返す Forwarding URL）
- フォーマット: JSON（例は下記）
- 受信保存先: `output/tradingview.jsonl`

---

## ngrok でローカルを公開する

1. ngrok をインストール・ログイン済みであることを確認します。
2. 別ターミナルで receiver を起動します：

```bash
source .venv/bin/activate
python receiver.py
```

3. 別のターミナルで ngrok を起動します：

```bash
ngrok http 8000
```

4. 実行結果に表示される `Forwarding`（https で始まる URL）をコピーします。

例： `https://abcd-12-34-56.ngrok-free.app`

5. その URL を TradingView の Webhook URL に設定します。

---

## TradingView 側のアラート設定（Pine + Alert JSON）

Pine スクリプト内でアラートを設定するとき、Alert message 欄に JSON を記述します。

例（Alert message 欄）:

```json
{"source":"tradingview","symbol":"JP225","price":{{close}},"time":"{{timenow}}"}
```

注意点:
- `{{close}}` や `{{timenow}}` は TradingView のテンプレートシンボルです。
- JSON の外側に余計なテキストを置かないでください（純粋な JSON を送ると `receiver.py` がパースしやすくなります）。

---

## セキュリティ：トークン認証の追加方法

1. 環境変数にトークンを設定します（例）：

```bash
export TV_WEBHOOK_SECRET="あなたのシークレット"
```

2. TradingView の Webhook URL にトークンを付与します：

```
https://abcd-12-34-56.ngrok-free.app/webhook?token=あなたのシークレット
```

3. `receiver.py` は環境変数 `TV_WEBHOOK_SECRET` を見て、受信時に `?token=` または `X-TV-Token` ヘッダの一致をチェックする実装にしてください（既存の `receiver.py` に簡易ヘッダチェックは未追加の場合、別途実装を行います）。

---

## テスト手順

1. ローカルで受信確認：

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{"source":"tradingview","symbol":"JP225","price":12345,"time":"now"}' \
http://127.0.0.1:8000/webhook
```

- 正常: HTTP 200 と `{"status":"ok"}` を受け取る。
- `output/tradingview.jsonl` に同内容が追記されることを確認します。

2. ngrok 経由のテスト：

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{"source":"tradingview","symbol":"JP225","price":12345,"time":"now"}' \
"https://abcd-12-34-56.ngrok-free.app/webhook"
```

3. トークン付き URL のテスト：

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{"source":"tradingview","symbol":"JP225","price":12345,"time":"now"}' \
"https://abcd-12-34-56.ngrok-free.app/webhook?token=あなたのシークレット"
```

---

## トラブルシュート

- 受信されない / 404 が返る:
  - ngrok の Forwarding URL を間違えていないか確認。
  - receiver が正しく起動しているか（`python receiver.py` を実行中か）確認。

- 受信はされるが `output/tradingview.jsonl` に書き込まれない:
  - `output/` ディレクトリのパーミッションを確認。
  - receiver のログや stdout を確認（`📩 Received:` が出ているか）。

- ngrok が起動しない / authtoken エラー:
  - `ngrok config add-authtoken <YOUR_TOKEN>` を行い、正しいトークンを設定してください。

---

## 付録: 例付きワークフロー

1. 仮想環境起動
```bash
source .venv/bin/activate
```
2. receiver 起動
```bash
python receiver.py
```
3. ngrok 起動
```bash
ngrok http 8000
```
4. TradingView の Webhook に ngrok の Forwarding URL を設定（必要なら ?token= を付与）
5. TradingView でアラート発砲、`output/tradingview.jsonl` を確認

---

© 2025 OTOMI CFD3_AutoSystem
