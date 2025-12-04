# 🚀 CFD3 DawnAI — 本番フェーズ セットアップ チェックリスト

## 📋 Step 1: TradingView アラート設定（計8個）

### サーバーURL
```
https://cfd3-autosystem-nxye.onrender.com/webhook
```

### 設定テーブル

| 銘柄 | 時間足 | アラート名 | Webhook URL | メッセージ |
|------|--------|-----------|-------------|-----------|
| JP225 | 30分 | JP225_30m_GO | https://cfd3-autosystem-nxye.onrender.com/webhook | JSON (下記) |
| JP225 | 4時間 | JP225_4H_GO | https://cfd3-autosystem-nxye.onrender.com/webhook | JSON (下記) |
| NAS100 | 30分 | NAS100_30m_GO | https://cfd3-autosystem-nxye.onrender.com/webhook | JSON (下記) |
| NAS100 | 4時間 | NAS100_4H_GO | https://cfd3-autosystem-nxye.onrender.com/webhook | JSON (下記) |
| GER40 | 30分 | GER40_30m_GO | https://cfd3-autosystem-nxye.onrender.com/webhook | JSON (下記) |
| GER40 | 4時間 | GER40_4H_GO | https://cfd3-autosystem-nxye.onrender.com/webhook | JSON (下記) |
| XAUUSD | 30分 | XAUUSD_30m_GO | https://cfd3-autosystem-nxye.onrender.com/webhook | JSON (下記) |
| XAUUSD | 4時間 | XAUUSD_4H_GO | https://cfd3-autosystem-nxye.onrender.com/webhook | JSON (下記) |

---

## 📌 Step 2: Webhook メッセージ設定

### メッセージ形式（JSON）

各アラートで以下をコピー＆ペーストしてください：

```json
{
  "symbol": "{{ticker}}",
  "direction": "{{strategy.direction}}",
  "signal": "GO",
  "price": "{{close}}",
  "time": "{{timenow}}"
}
```

### アラート設定の詳細

- **発火タイミング**: バーの終値ごと（Once per bar close）
- **Webhook Method**: POST
- **Content-Type**: application/json
- **URL**: https://cfd3-autosystem-nxye.onrender.com/webhook

---

## 🧪 Step 3: 動作確認テスト

### テスト手順

1. **1つのアラートだけをアクティベート**
   - 例：`JP225_30m_GO`

2. **TradingView チャートを確認**
   - 30分足で新しいバーが確定するのを待つ
   - または手動でシグナル条件をトリガー

3. **Render ログを確認**
   ```
   Render Dashboard → Logs (tail -f)
   ```

4. **以下のメッセージが表示されたら成功** ✅
   ```
   [Webhook] Received: {
     "symbol": "JP225",
     "direction": "BUY",
     "signal": "GO",
     "price": 30000.5,
     "time": "2025-12-04 15:30:00"
   }
   ```

---

## ✅ 事前確認チェックリスト

- [ ] Render が最新コミット（ab003d67）でデプロイ完了したか確認
- [ ] `/test` エンドポイントで健全性確認
  ```
  GET https://cfd3-autosystem-nxye.onrender.com/test
  ```
  期待値: `{"status": "ok", "version": "200 (FIXED)"}`

- [ ] `/webhook` エンドポイント存在確認
  ```
  POST https://cfd3-autosystem-nxye.onrender.com/webhook
  ```

- [ ] TradingView インジケータが正常に動作しているか確認
  - 銘柄データが取得できているか
  - シグナルロジックが正しく機能しているか

---

## 🔧 トラブルシューティング

### ❌ 「[Webhook] Received」が表示されない

**対策1: URL を再確認**
```
✅ https://cfd3-autosystem-nxye.onrender.com/webhook
❌ https://cfd3-autosystem-nxye.onrender.com/analyze/image
```

**対策2: JSON メッセージ形式を確認**
- TradingView で JSON が有効か確認
- `{{ticker}}` や `{{close}}` が正しく展開されているか

**対策3: TradingView ログを確認**
- TradingView → Alerts → Alert History
- 実際にアラートが発火しているか確認

**対策4: Render デプロイ確認**
- Render Dashboard で最新デプロイが成功しているか確認
- ビルドログにエラーがないか確認

### ❌ Render が 502 Bad Gateway を返す

**原因**: デプロイがまだ完了していない可能性

**対策**:
1. Render Dashboard → Deployments を確認
2. 数分待機
3. 再度テスト

### ❌ メッセージは受け取るが IFD が生成されない

**原因**: `analyze_unified_ifd()` が未実装または失敗

**対策**:
1. Render ログでエラーを確認
2. `server/analyze_unified_ifd.py` が存在するか確認
3. 関数のシグネチャを確認

---

## 🚀 本番フェーズへの移行

### 全アラートアクティベート前の確認

- [ ] 1銘柄でテスト完了 ✅
- [ ] Render ログで正常動作確認 ✅
- [ ] IFD テーブルが生成されることを確認 ✅

### 本番運用開始

1. **残り7つのアラートをアクティベート**
   ```
   JP225_4H_GO
   NAS100_30m_GO
   NAS100_4H_GO
   GER40_30m_GO
   GER40_4H_GO
   XAUUSD_30m_GO
   XAUUSD_4H_GO
   ```

2. **リアルタイム監視**
   - Render ログで受信状況を確認
   - IFD の質を評価
   - 必要に応じてパラメータ調整

3. **定期的なバックアップ**
   - 毎日のログ保存
   - GitHub へのコード更新

---

## 📞 サポート情報

- **Server URL**: https://cfd3-autosystem-nxye.onrender.com
- **GitHub**: https://github.com/furuta61/CFD3_AutoSystem
- **Render Dashboard**: https://dashboard.render.com

---

**最終更新**: 2025-12-04
**ステータス**: 🟢 本番運用準備完了
