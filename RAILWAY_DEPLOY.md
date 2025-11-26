# Railway デプロイ設定

## 環境変数の設定

Railway のダッシュボードで以下の環境変数を設定してください:

```
OPENAI_API_KEY=sk-proj-...あなたのOpenAI APIキー...
PORT=8080
```

## デプロイ手順

### 1. Railway CLIのインストール
```bash
npm i -g @railway/cli
```

### 2. Railwayにログイン
```bash
railway login
```

### 3. プロジェクトを初期化
```bash
cd /Users/otomi/Desktop/vs\ code/CFD3_AutoSystem
railway init
```

### 4. デプロイ
```bash
railway up
```

### 5. ドメインを設定
Railway ダッシュボードで:
1. Settings → Networking
2. "Generate Domain" をクリック
3. 生成されたURLをメモ（例: `https://your-app.up.railway.app`）

## アクセス方法

デプロイ後のURL:
- UI: `https://your-app.up.railway.app/ui`
- Webhook: `https://your-app.up.railway.app/webhook`
- AI解析: `https://your-app.up.railway.app/analyze/swing_multi`

## 注意事項

- **data/フォルダのCSVファイル**: Railwayにもアップロードされますが、データ更新が必要な場合は再デプロイが必要
- **ログ確認**: `railway logs` コマンドで確認可能
- **無料枠**: 月5ドル相当のクレジットまで無料
- **スリープなし**: 常時起動（Renderと違い）

## トラブルシューティング

### デプロイが失敗する場合
```bash
railway logs
```

### 環境変数を確認
```bash
railway variables
```

### 再デプロイ
```bash
railway up --detach
```
