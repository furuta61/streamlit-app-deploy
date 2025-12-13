# Dawn IFD Trader - 新アーキテクチャ

## 🏗️ プロジェクト構造

```
CFD3_AutoSystem/
├── backend/          # FastAPI バックエンド
│   └── main.py       # メインAPI (ポート8000)
├── models/           # AIモデル・計算エンジン
│   ├── __init__.py
│   └── ifd_engine.py # IFD計算ロジック
├── frontend/         # Webフロントエンド
│   └── index.html    # シングルページアプリ
├── server/           # 既存システム（互換性維持）
│   ├── webhook_server.py  # 既存API (ポート8080)
│   └── analyze_unified_ifd.py
├── direction_model.pkl    # AIモデル（方向性予測）
├── tp_sl_model.pkl        # AIモデル（TP/SL最適化）
└── README_NEW_ARCH.md     # このファイル
```

## 🚀 クイックスタート

### 1. バックエンドAPI起動

```bash
cd /Users/otomi/Desktop/vs\ code/CFD3_AutoSystem
source .venv/bin/activate
python backend/main.py
```

→ http://localhost:8000 で起動

### 2. フロントエンド起動

```bash
# シンプルなHTTPサーバーで起動
cd frontend
python -m http.server 3000
```

→ http://localhost:3000 でアクセス

### 3. APIテスト

#### ヘルスチェック
```bash
curl http://localhost:8000/health
```

#### 銘柄一覧
```bash
curl http://localhost:8000/symbols
```

#### IFD分析
```bash
curl -X POST http://localhost:8000/analyze \
  -F "csv_file=@data/FOREXCOM_JP225_60.csv" \
  -F "symbol=JP225" \
  -F "timeframe=1h" \
  -F "sentiment_pos=60" \
  -F "sentiment_neg=15"
```

## 📡 API仕様

### POST /analyze

**リクエスト:**
- `csv_file`: OHLC CSV (time,open,high,low,close,volume)
- `symbol`: JP225, NAS100, GER40, XAUUSD
- `timeframe`: 30m, 1h, 4h
- `sentiment_pos`: ポジティブ感情 (0-100)
- `sentiment_neg`: ネガティブ感情 (0-100)

**レスポンス例:**
```json
{
  "symbol": "JP225",
  "timeframe": "1h",
  "decision": "GO",
  "direction": "buy",
  "entry_price": 49550.0,
  "take_profit_1": 49775.0,
  "take_profit_2": 50000.0,
  "stop_loss": 49325.0,
  "order_type": "指値",
  "stars": "★★★★★",
  "ai_score": 0.756,
  "ai_judge": "GO",
  "technicals": {
    "rsi": 52.3,
    "sma25": 49500.5,
    "sma75": 49200.0,
    "macd": 120.5,
    "signal": 95.3,
    "atr": 150.0
  },
  "sentiment": {
    "positive": 60,
    "negative": 15,
    "neutral": 25
  }
}
```

## 🔧 カスタマイズ

### GMO現在値の更新

`models/ifd_engine.py` の `GMO_PRICES` を編集:

```python
GMO_PRICES = {
    "JP225": {"bid": 49550.6, "ask": 49553.6},
    "NAS100": {"bid": 25623.0, "ask": 25623.7},
    "GER40": {"bid": 23757.5, "ask": 23760.5},
    "XAUUSD": {"bid": 4214.78, "ask": 4214.93},
}
```

### リスク係数の調整

`models/ifd_engine.py` の `build_ifd_from_gmo()` 内:

```python
risk_k = 1.5  # SL幅 = 1.5×ATR
tp1_k = 1.5   # TP1幅 = 1.5×ATR
tp2_k = 3.0   # TP2幅 = 3.0×ATR
```

## 📊 既存システムとの互換性

既存の `/final` エンドポイント（ポート8080）は引き続き動作します:

```bash
# 既存システム起動
uvicorn server.webhook_server:app --host 127.0.0.1 --port 8080 --reload
```

新システム（ポート8000）と並行して使用可能です。

## 🎯 主な改善点

### 1. クリーンな構造
- **backend/**: API層（FastAPI）
- **models/**: ビジネスロジック層
- **frontend/**: プレゼンテーション層

### 2. シンプルなAPI
- RESTful設計
- Swagger UI自動生成 (`/docs`)
- CORS対応（フロントエンド連携）

### 3. 再利用可能なモジュール
- `models/ifd_engine.py` は独立して使用可能
- 他のプロジェクトからもインポート可能

### 4. テスト容易性
- 各モジュールが疎結合
- ユニットテスト追加が容易

## 📝 開発ロードマップ

### Phase 1 (完了)
- ✅ Backend API構築
- ✅ Models層の整理
- ✅ Frontend UI作成

### Phase 2 (次のステップ)
- スクリーンショット分析機能の統合
- リアルタイム価格更新
- チャート表示機能

### Phase 3 (将来)
- React/Next.jsへの移行
- バックテスト機能
- トレード履歴管理

## 🛠️ トラブルシューティング

### ポート競合
```bash
# ポート8000が使用中の場合
lsof -ti:8000 | xargs kill -9

# ポート8080が使用中の場合
lsof -ti:8080 | xargs kill -9
```

### モデルが見つからない
```bash
# ダミーモデル作成
python create_dummy_models.py
```

### CORS エラー
`backend/main.py` の CORS設定を確認:
```python
allow_origins=["http://localhost:3000"]  # フロントエンドのURLを指定
```

## 📞 サポート

質問や問題がある場合は、既存の `README.md` も参照してください。
