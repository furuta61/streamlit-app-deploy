# TradingView → ngrok → receiver.py → ensemble データフロー概要

## 📘 概要

このシステムは **TradingView のアラート**をトリガーとして受信し、  
ローカル環境での自動データ処理パイプラインを実現します。  

受信したデータは即時に `output/tradingview.jsonl` に保存され、  
その後 `market_data_ensemble.py` などのモジュールで  
マーケットデータに統合・活用されます。

---

## ⚙️ データフロー構成図


TradingView (A: アラート送信)
│
│ ① HTTP POST （Webhook）
▼
ngrok (B: 公開トンネル)
│
│ ② 外部からローカルの Flask サーバーへ中継
▼
receiver.py (C: Webhook 受信サーバー)
│
│ ③ JSON データを output/tradingview.jsonl に即時保存
▼
output/tradingview.jsonl
│
│ ④ market_data_ensemble.py で読み込み・統合
▼
分析・自動売買・ダッシュボード更新など


---

## 🔄 処理ステップ詳細

| ステップ | 処理内容 | 実装/ツール |
|-----------|-----------|-------------|
| ① | TradingView がアラートを送信（Webhook JSON POST） | TradingView Alert |
| ② | ngrok が外部リクエストをローカルの port:8000 に転送 | ngrok |
| ③ | receiver.py が `/webhook` で受信し、JSONを `output/tradingview.jsonl` に追記 | Flask (Python) |
| ④ | ファイルは flush + fsync で即時ディスク反映 | receiver.py |
| ⑤ | ensemble スクリプトが tradingview.jsonl を参照して統合処理 | market_data_ensemble.py |

---

## 🧩 主要ファイル構成



CFD3_AutoSystem/
├── receiver.py # Webhook受信スクリプト（Flask）
├── market_data_tradingview.py # TradingViewデータ読み込み
├── market_data_ensemble.py # データ統合処理
├── output/
│ └── tradingview.jsonl # 受信データのログ（JSON Lines形式）
└── docs/
└── pipeline_overview.md # 本ドキュメント


---

## 🔐 セキュリティ強化（オプション）

受信エンドポイント `/webhook` に対して  
`?token=YOUR_SECRET` を付けたリクエストのみを許可する  
簡易認証を追加できます。

- TradingView の Webhook URL:  
  `https://xxxx.ngrok-free.dev/webhook?token=YOUR_SECRET`
- `receiver.py` 側で `TV_WEBHOOK_SECRET` を環境変数として設定。

---

## 🧠 運用メモ

| 項目 | 内容 |
|------|------|
| 公開URL確認 | `ngrok http 8000` 実行後、 `Forwarding https://xxxx.ngrok-free.dev` のURLを使用 |
| ローカル確認 | `curl -X POST http://127.0.0.1:8000/webhook -d '{"test":true}'` |
| ログ確認 | `tail -n 10 output/tradingview.jsonl` |
| ngrokログUI | [http://127.0.0.1:4040](http://127.0.0.1:4040) |
| 停止 | Ctrl + C で Flask/Ngrok を終了 |

---

## 🚀 今後の拡張案

- Token 認証の導入（安全性向上）
- Slack / LINE 通知機能の追加
- tradingview.jsonl の自動ローテーション
- ensemble 結果の可視化（Streamlit など）

---

© 2025 OTOMI CFD3_AutoSystem
