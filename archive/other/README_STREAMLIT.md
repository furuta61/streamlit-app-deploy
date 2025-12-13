# CFD3_AutoSystem - IFD自動生成アプリ

Streamlit Web UIでiPhoneスクリーンショットから自動的にIFD注文を生成します。

## 🚀 デプロイ済みアプリ

[Streamlit Cloudでアプリを開く](あなたのアプリURL)

## 機能

- 📸 GPT Vision OCRでスクリーンショットから価格抽出（100%精度）
- 🎯 STRONG_GO/GO判定による自動ロット・TP計算
- 📊 IFDテーブル自動生成（Markdown形式）
- 🇯🇵 日本語対応

## ローカル実行

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="your-api-key"
streamlit run app.py
```

## 環境変数

Streamlit Cloudの「Settings > Secrets」に以下を設定:

```toml
OPENAI_API_KEY = "sk-proj-..."
```
