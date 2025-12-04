# TradingView Alert Setup Guide

## 📋 4銘柄 × 2時間足 アラート設定

### Step 1: Webhook URL設定

**Webhook Endpoint:**
```
https://cfd3-autosystem-nxye.onrender.com/webhook
```

---

## 🎯 各銘柄の設定（計8個のアラート）

### 1️⃣ JP225

#### Alert Name (30分足)
```
JP225_30m_GO
```

#### Alert Name (4時間足)
```
JP225_4H_GO
```

#### Alert Message (両方共通)
```json
{
  "symbol": "{{ticker}}",
  "direction": "{{strategy.direction}}",
  "signal": "GO",
  "price": "{{close}}",
  "time": "{{timenow}}"
}
```

#### Webhook URL
```
https://cfd3-autosystem-nxye.onrender.com/webhook
```

#### 条件
- ✅ バーの終値ごと
- ✅ Once per bar close

---

### 2️⃣ NAS100

#### Alert Name (30分足)
```
NAS100_30m_GO
```

#### Alert Name (4時間足)
```
NAS100_4H_GO
```

#### Alert Message
```json
{
  "symbol": "{{ticker}}",
  "direction": "{{strategy.direction}}",
  "signal": "GO",
  "price": "{{close}}",
  "time": "{{timenow}}"
}
```

#### Webhook URL
```
https://cfd3-autosystem-nxye.onrender.com/webhook
```

---

### 3️⃣ GER40

#### Alert Name (30分足)
```
GER40_30m_GO
```

#### Alert Name (4時間足)
```
GER40_4H_GO
```

#### Alert Message
```json
{
  "symbol": "{{ticker}}",
  "direction": "{{strategy.direction}}",
  "signal": "GO",
  "price": "{{close}}",
  "time": "{{timenow}}"
}
```

#### Webhook URL
```
https://cfd3-autosystem-nxye.onrender.com/webhook
```

---

### 4️⃣ XAUUSD

#### Alert Name (30分足)
```
XAUUSD_30m_GO
```

#### Alert Name (4時間足)
```
XAUUSD_4H_GO
```

#### Alert Message
```json
{
  "symbol": "{{ticker}}",
  "direction": "{{strategy.direction}}",
  "signal": "GO",
  "price": "{{close}}",
  "time": "{{timenow}}"
}
```

#### Webhook URL
```
https://cfd3-autosystem-nxye.onrender.com/webhook
```

---

## 🧪 Step 2: 動作テスト（1銘柄でOK）

### テスト手順

1. **TradingView Alert を1つ選ぶ**（例：JP225_30m_GO）
2. **「Test Alert」をクリック**
3. **Render ログを確認**

### ✅ 成功の判定

```
[INFO] Webhook received: {
  "symbol": "JP225",
  "direction": "BUY",
  "signal": "GO",
  "price": 30000.5,
  "time": "2025-12-04 15:30:00"
}
```

が表示されれば成功です。

---

## 📊 Step 3: IFD出力確認

### 期待される出力

Render のログに以下のような形式が表示されます：

```
[INFO] IFD Table:
trade_mode | 銘柄   | 方向 | entry  | SL    | TP1    | TP2    | 判定 | 推奨度 | コメント
-----------|--------|------|--------|-------|--------|--------|------|--------|----------
HYBRID     | JP225  | BUY  | 30000  | 29950 | 30120  | 30240  | GO   | ★★★★★ | 4H強トレンド優先
HYBRID     | NAS100 | BUY  | 20000  | 19950 | 20080  | 20160  | GO   | ★★★★☆ | GMO強上抜け
```

### ❌ トラブルシューティング

**「Webhook received」が出ない場合**

1. URL を再確認：`/webhook` か `/analyze/image` か確認
2. メッセージフォーマットを確認（JSONが有効か）
3. 以下を試す：

```
https://cfd3-autosystem-nxye.onrender.com/analyze/image
```

**デプロイがまだ完了していない場合**

- Render ダッシュボード → Deployments → 進行状況確認
- 数分待機後、再度テスト

---

## 🚀 完全設定チェックリスト

- [ ] 4銘柄 × 2時間足 = 計8個のアラート作成
- [ ] Webhook URL が正しい（https://cfd3-autosystem-nxye.onrender.com/webhook）
- [ ] メッセージフォーマットが JSON 形式
- [ ] 「バーの終値ごと」設定を確認
- [ ] 1銘柄でテストアラート送信
- [ ] Render ログで「Webhook received」確認
- [ ] IFD テーブルが出力されていることを確認

---

## 📌 補足

- アラート間隔：同じ銘柄の 30m と 4H は独立して発動（重複OK）
- リアルタイム対応：終値確定後、即座に IFD 生成
- 本番運用：すべてのアラートをアクティベート → 自動運用開始

