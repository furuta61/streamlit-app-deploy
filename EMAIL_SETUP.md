# 📧 メール通知機能 セットアップガイド

## 概要

CFD3 DawnAI の IFD生成結果を、自動的にメール通知する機能です。

**フロー：**
```
TradingView Alert
    ↓
/webhook (受信)
    ↓
/ai_ifd_mail (メール送信)
    ↓
📧 メール通知
```

---

## 🚀 セットアップ手順

### Step 1: Render 環境変数設定

Render Dashboard で以下の環境変数を登録してください。

#### Gmail の場合

| 環境変数 | 値 | 説明 |
|---------|-----|------|
| `MAIL_USERNAME` | `your-email@gmail.com` | 送信元メールアドレス |
| `MAIL_PASSWORD` | `xxxx xxxx xxxx xxxx` | App Password（16文字、空白区切り） |
| `MAIL_FROM` | `your-email@gmail.com` | 送信元アドレス（USERNAME と同じ） |
| `MAIL_TO` | `recipient@example.com` | 受信者メールアドレス |
| `MAIL_PORT` | `587` | SMTP ポート |
| `MAIL_SERVER` | `smtp.gmail.com` | SMTP サーバー |
| `MAIL_TLS` | `True` | TLS有効化 |
| `MAIL_SSL` | `False` | SSL無効化 |

#### iCloud Mail の場合

| 環境変数 | 値 |
|---------|-----|
| `MAIL_USERNAME` | `your-email@icloud.com` |
| `MAIL_PASSWORD` | `xxxx-xxxx-xxxx-xxxx` | App Password（iCloud） |
| `MAIL_FROM` | `your-email@icloud.com` |
| `MAIL_TO` | `recipient@example.com` |
| `MAIL_PORT` | `587` |
| `MAIL_SERVER` | `smtp.mail.me.com` |
| `MAIL_TLS` | `True` |
| `MAIL_SSL` | `False` |

#### Outlook/Hotmail の場合

| 環境変数 | 値 |
|---------|-----|
| `MAIL_USERNAME` | `your-email@outlook.com` |
| `MAIL_PASSWORD` | `your-password` |
| `MAIL_FROM` | `your-email@outlook.com` |
| `MAIL_TO` | `recipient@example.com` |
| `MAIL_PORT` | `587` |
| `MAIL_SERVER` | `smtp-mail.outlook.com` |
| `MAIL_TLS` | `True` |
| `MAIL_SSL` | `False` |

---

## 🔐 Gmail App Password の取得方法

1. **Google アカウントを開く**
   ```
   https://myaccount.google.com
   ```

2. **左メニュー → 「セキュリティ」**

3. **「App Passwords」をクリック**
   - 2段階認証が有効になっていることを確認
   - アプリ：`メール`
   - デバイス：`Windows コンピュータ`（または使用デバイス）
   - 選択して生成

4. **16文字のパスワードが表示される**
   - コピーして Render の `MAIL_PASSWORD` に貼り付け

---

## 📬 iCloud App Password の取得方法

1. **iCloud Settings を開く**
   ```
   https://appleid.apple.com
   ```

2. **「セキュリティ」セクション**

3. **「App Passwords」**
   - App: `メール`
   - Device: 自分のデバイス
   - 生成

4. **App Password をコピー**
   - Render の `MAIL_PASSWORD` に貼り付け

---

## 🧪 テスト方法

### テスト1: ローカルで動作確認

```bash
# 環境変数を .env ファイルに記述
echo "MAIL_USERNAME=your-email@gmail.com" >> .env
echo "MAIL_PASSWORD=xxxx xxxx xxxx xxxx" >> .env
echo "MAIL_FROM=your-email@gmail.com" >> .env
echo "MAIL_TO=recipient@example.com" >> .env
echo "MAIL_PORT=587" >> .env
echo "MAIL_SERVER=smtp.gmail.com" >> .env

# サーバー起動
cd server
python -m uvicorn webhook_server:app --reload
```

### テスト2: TradingView アラート送信

1. **TradingView でアラート送信**
   ```
   POST https://localhost:8080/webhook
   ```

2. **/test ページで受信確認**
   ```
   http://localhost:8080/test
   ```

3. **/ai_ifd_mail でメール送信**
   ```
   http://localhost:8080/ai_ifd_mail
   ```

4. **メール受信確認** ✅

---

## 🌐 Render でのテスト

### テスト手順

1. **Render にデプロイ完了を待つ**

2. **TradingView からアラート送信**
   ```
   POST https://cfd3-autosystem-nxye.onrender.com/webhook
   ```

3. **/test でデータ確認**
   ```
   https://cfd3-autosystem-nxye.onrender.com/test
   ```

4. **/ai_ifd_mail でメール送信テスト**
   ```
   https://cfd3-autosystem-nxye.onrender.com/ai_ifd_mail
   ```

5. **受信メールアドレスに IFD が届く** 📧

---

## 🔧 トラブルシューティング

### ❌ "メール機能が有効化されていません"

**原因:** 環境変数が設定されていない

**対策:**
```
Render Dashboard 
→ Environment 
→ MAIL_USERNAME, MAIL_PASSWORD などを追加
→ "Deploy" で再デプロイ
```

### ❌ "認証に失敗しました"

**原因:** メールアドレス or App Password が間違っている

**対策:**
1. App Password を再生成（16文字確認）
2. `MAIL_USERNAME` と `MAIL_FROM` が一致しているか確認
3. `MAIL_PORT` が `587` か確認

### ❌ "MAIL_SERVER への接続に失敗"

**原因:** SMTP サーバーアドレスが間違っている

**対策:**
- Gmail: `smtp.gmail.com`
- iCloud: `smtp.mail.me.com`
- Outlook: `smtp-mail.outlook.com`

を確認してください。

### ❌ メールが届かない

**対策:**
1. Render ログで error メッセージを確認
2. メールのスパムフォルダを確認
3. メールアドレスの入力ミスを確認

---

## 📊 使用例

### シンプル版：即座にメール送信

```bash
curl https://cfd3-autosystem-nxye.onrender.com/ai_ifd_mail
```

**レスポンス例：**
```json
{
  "status": "ok",
  "message": "メール送信成功",
  "sent_to": "recipient@example.com",
  "symbols": ["JP225", "NAS100"]
}
```

### 本番運用：Webhook → メール自動パイプライン

1. TradingView Alert 発火
2. `/webhook` で受信
3. `/ai_ifd_mail` で自動メール送信（Python script 等で自動化可能）

---

## 🔮 今後の拡張

- [ ] 複数受信者対応
- [ ] 定期的なニュースサマリーメール
- [ ] Discord / Slack 連携
- [ ] LINE 通知
- [ ] MT5 自動売買連携

---

## 📞 サポート

問題が発生した場合：

1. **Render ログを確認**
   ```
   Render Dashboard → Logs
   ```

2. **エラーメッセージを記録**

3. **GitHub に Issue を作成**
   ```
   https://github.com/furuta61/CFD3_AutoSystem/issues
   ```

---

**最終更新:** 2025-12-04  
**バージョン:** CFD3 DawnAI v200
