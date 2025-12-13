# TradingView アラート設定ガイド
## CFD3 DawnAI — 自動IFD生成パイプライン

---

## 📋 アラート設定情報

### Webhook URL（共通）
```
https://cfd3-autosystem-nxye.onrender.com/webhook
```

### メッセージ テンプレート（全アラート共通）
```json
{
  "symbol": "{{ticker}}",
  "direction": "{{strategy.direction}}",
  "signal": "GO",
  "price": "{{close}}",
  "time": "{{timenow}}",
  "news": "AUTO"
}
```

---

## 🎯 設定対象アラート（8個）

### グループ1: 日本225（JP225）
| # | 銘柄 | タイムフレーム | アラート名 | 優先度 |
|---|------|-------------|---------|--------|
| 1 | 日本225 | 30分足 | JP225_30m_GO | 🔴 高 |
| 2 | 日本225 | 4時間足 | JP225_4H_GO | 🟠 中 |

### グループ2: NAS100（米国NQ100）
| # | 銘柄 | タイムフレーム | アラート名 | 優先度 |
|---|------|-------------|---------|--------|
| 3 | NAS100 | 30分足 | NAS100_30m_GO | 🔴 高 |
| 4 | NAS100 | 4時間足 | NAS100_4H_GO | 🟠 中 |

### グループ3: GER40（ドイツ40）
| # | 銘柄 | タイムフレーム | アラート名 | 優先度 |
|---|------|-------------|---------|--------|
| 5 | GER40 | 30分足 | GER40_30m_GO | 🔴 高 |
| 6 | GER40 | 4時間足 | GER40_4H_GO | 🟠 中 |

### グループ4: XAUUSD（金スポット）
| # | 銘柄 | タイムフレーム | アラート名 | 優先度 |
|---|------|-------------|---------|--------|
| 7 | XAUUSD | 30分足 | XAUUSD_30m_GO | 🔴 高 |
| 8 | XAUUSD | 4時間足 | XAUUSD_4H_GO | 🟠 中 |

---

## 🔧 TradingView設定手順

### ステップ1: TradingViewにログイン
```
https://www.tradingview.com → ログイン
```

### ステップ2: アラート作成（各銘柄×2回繰り返す）

**例: JP225_30m_GO**

1. TradingViewチャート上で日本225（JP225）を開く
2. タイムフレームを **30分** に設定
3. **アラート** → **新規アラート** をクリック
4. 以下を入力：

| 項目 | 値 |
|------|-----|
| アラート名 | `JP225_30m_GO` |
| 条件 | （既存のシグナル条件またはカスタム） |
| Webhook URL | `https://cfd3-autosystem-nxye.onrender.com/webhook` |
| メッセージ | 下記の JSON |

**メッセージ欄に貼り付け:**
```json
{
  "symbol": "{{ticker}}",
  "direction": "{{strategy.direction}}",
  "signal": "GO",
  "price": "{{close}}",
  "time": "{{timenow}}",
  "news": "AUTO"
}
```

5. **アラートを作成** をクリック

### ステップ3: 同じプロセスを7回繰り返す

4時間足のアラートも同様に設定：

```
JP225 → 30分足アラート
JP225 → 4時間足アラート
NAS100 → 30分足アラート
NAS100 → 4時間足アラート
GER40 → 30分足アラート
GER40 → 4時間足アラート
XAUUSD → 30分足アラート
XAUUSD → 4時間足アラート
```

---

## ✅ 動作確認チェックリスト

### Webhook接続確認

| ステップ | 確認内容 | 状態 |
|---------|---------|------|
| 1 | Render ダッシュボード → Logs | 待機中 |
| 2 | TradingView アラート作成 | 完了 |
| 3 | テストアラート送信 | 実行予定 |
| 4 | Render Live Tail ログ確認 | 確認予定 |

### 期待されるログ出力

テストアラートを送信したら、Render の Live Tail で以下が表示される：

```
[Webhook] Received signal GO for JP225
[AI] Raw response: {"entry": XXXXX, "tp1": XXXXX, "sl": XXXXX, "comment": "..."}
[AI] Generated IFD plan → Entry: XXXXX / TP1: XXXXX / SL: XXXXX
```

**3行すべてが出れば完全動作！** ✅

---

## 🧪 テスト手順

### 1️⃣ Render Live Tail を開く
```
https://dashboard.render.com/services/cfd3-autosystem → Logs → Live Tail
```

### 2️⃣ TradingView でテストアラートを送信

TradingView アラート画面から **テスト送信** （またはアラート条件を満たす）

### 3️⃣ ログを確認

Live Tail に以下が出れば成功：
```
[Webhook] Received signal GO for JP225
[AI] Generated IFD plan → Entry: XXXXX / TP1: XXXXX / SL: XXXXX
```

### 4️⃣ IFD データを確認

Render ログに含まれる以下を確認：
- **Entry**: エントリー価格
- **TP1**: テイクプロフィット1
- **SL**: ストップロス

---

## 🔐 セキュリティ注意事項

- Webhook URL は機密情報です。外部に共有しないでください
- OPENAI_API_KEY は Render の Environment に安全に保管されています
- TradingView アラートログは定期的に確認してください

---

## 📞 トラブルシューティング

### ❌ Render にアラートが到達しない

**確認項目:**
1. Webhook URL が正確か確認
2. TradingView アラート画面で URL を再確認
3. メッセージ形式が JSON として正しいか確認

### ⚠️ ログに 1行だけ出ている

```
[Webhook] Received signal GO for JP225
```

**原因:** OPENAI_API_KEY が未設定または有効期限切れ  
**対策:** Render → Environment → OPENAI_API_KEY を確認・更新

### ❌ ログに何も出ない

**原因:** Start Command が誤っている  
**対策:** Render → Settings → `uvicorn server.webhook_server:app --host 0.0.0.0 --port $PORT` を確認

---

## 📊 設定完了チェック

```
✅ 8個のアラートをすべて作成
✅ Webhook URL を統一
✅ メッセージテンプレートを統一
✅ テストアラートで Render ログに 3行出力を確認
✅ IFD データ（Entry/TP1/SL）が正確に生成されることを確認
```

すべてチェックできれば、**自動IFD生成パイプラインの完成！** 🎉

---

## 📝 記録用

### 作成したアラート

- [ ] #1: JP225_30m_GO
- [ ] #2: JP225_4H_GO
- [ ] #3: NAS100_30m_GO
- [ ] #4: NAS100_4H_GO
- [ ] #5: GER40_30m_GO
- [ ] #6: GER40_4H_GO
- [ ] #7: XAUUSD_30m_GO
- [ ] #8: XAUUSD_4H_GO

### テスト実行日時

- テスト送信日時: _______________
- Render ログ確認: ✅ / ❌
- IFD データ確認: ✅ / ❌
