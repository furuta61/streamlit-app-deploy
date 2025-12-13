# CFD3 AutoSystem 運用マニュアル（最終版）

## 概要
CFD3 AutoSystem は、CFD 市況イベント（`events.csv`）を解析し、GPT を利用してセンチメント・スコアリングを自動付与します。  
出力はローカルの **Google Drive 同期フォルダ** に保存され、Google Drive アプリが自動でクラウドに同期します。

---

## 実行方法

### Dry-run（アップロードなし、テストモード）
```bash
~/Desktop/CFD3_AutoSystem/.venv/bin/python3 ~/Desktop/CFD3_AutoSystem/weekly_events_update.py \
  --dry-run --file events.csv --service-account ~/.secrets/drive-sa.json
```

### 本番実行（ローカルGoogle Driveに保存）
```bash
~/Desktop/CFD3_AutoSystem/.venv/bin/python3 ~/Desktop/CFD3_AutoSystem/weekly_events_update.py \
  --file events.csv --service-account ~/.secrets/drive-sa.json
```

出力ファイル例：

```
$LOCAL_GOOGLE_DRIVE/CFD3Pro/events_scored_YYYYMMDD_HHMM.csv
```

## 環境設定

### LOCAL_GOOGLE_DRIVE の設定（済）

`~/.zshrc` に以下を追記済みです：

```bash
# Added by CFD3_AutoSystem
export LOCAL_GOOGLE_DRIVE="/Users/otomi/Google ドライブ"
```

反映：

```bash
source ~/.zshrc
```

## OpenAI APIキー管理

### 登録場所（推奨）
macOS Keychain（推奨）

登録例（Keychain に追加する例）:

```bash
security add-generic-password -a openai -s openai -w "sk-xxxxxx"
```

呼び出し（確認）:

```bash
security find-generic-password -a openai -w
```

代替：環境変数

```bash
export OPENAI_API_KEY="sk-xxxxxx"
```

再発行: https://platform.openai.com/account/api-keys

## コスト管理（目安）

モデル	単価（おおよそ）	1イベント当たりコスト目安
GPT‑4o	約$0.005/1K tokens	約¥0.1〜¥0.3
GPT‑4o‑mini	約$0.001/1K tokens	約¥0.03〜¥0.1

例：イベント100件 × GPT‑4o‑mini = 約¥10〜¥30／週。

確認方法：

```bash
open https://platform.openai.com/usage
```

## Shared Drive への移行手順（Drive自動アップロード再開）

方法①：サービスアカウントを共有ドライブに追加

1. Drive 管理者で Shared Drive を作成
2. サービスアカウントの `client_email` をメンバーに追加（権限：編集者）
3. スクリプト内の保存先を Shared Drive のパスに変更

方法②：OAuth認証を利用（PyDrive2）

1. Google Cloud Console → OAuth クライアントIDを作成
2. `client_secrets.json` をプロジェクトルートに配置
3. 初回実行時にブラウザで認証を行い、`credentials.json` が自動生成されます
4. Drive API 書き込みが有効になります

## 自動実行設定（launchd）

設定ファイル：`~/Library/LaunchAgents/com.cfd3.autosystem.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cfd3.autosystem</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/otomi/Desktop/CFD3_AutoSystem/.venv/bin/python3</string>
        <string>/Users/otomi/Desktop/CFD3_AutoSystem/weekly_events_update.py</string>
        <string>--file</string>
        <string>events.csv</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>7</integer>
        <key>Weekday</key><integer>2</integer> <!-- 月曜 -->
    </dict>
    <key>StandardOutPath</key><string>/tmp/cfd3_autosystem.log</string>
    <key>StandardErrorPath</key><string>/tmp/cfd3_autosystem.err</string>
</dict>
</plist>
```

ロード：

```bash
launchctl load ~/Library/LaunchAgents/com.cfd3_autosystem.plist
```

確認：

```bash
launchctl list | grep cfd3
```

ログ：

```bash
tail -f /tmp/cfd3_autosystem.log
```

## 保守・トラブル対応

| 症状 | 原因 | 対処 |
|---|---|---|
| storageQuotaExceeded | サービスアカウントに容量がない | ローカル同期方式に切替（現在の構成） |
| client_secrets.json not found | OAuth構成なし | Drive API使用を無効化またはShared Drive構成に変更 |
| GPT呼び出し失敗 | ネットワーク / API制限 | 自動リトライ（3回）後にログ確認 |
| ファイルがDriveに同期されない | Driveアプリ停止 | Driveアプリを再起動 or 再ログイン |

### メンテナンス

手動再実行:

```bash
python ~/Desktop/CFD3_AutoSystem/weekly_events_update.py
```

再スコアリング（既存CSV）:

```bash
python weekly_events_update.py --file events.csv --recalc
```

launchd再登録:

```bash
launchctl unload ~/Library/LaunchAgents/com.cfd3.autosystem.plist
launchctl load ~/Library/LaunchAgents/com.cfd3.autosystem.plist
```

ログ確認:

```bash
tail -n 50 /tmp/cfd3_autosystem.log
```

最終更新: 2025-10-30 02:44
# CFD3_AutoSystem - 操作メモ（簡易）

目的: 最小の手順で API キーを設定し、dry-run → 本番送信を行う方法を示します。

前提:
- スクリプトは `~/Desktop/CFD3_AutoSystem` に配置されています。
- こちらでは API キーをチャットに貼らず、Keychain（keyring）か環境変数で管理します。

1) OpenAI API キーを Keychain に保存（推奨）

```bash
python3 - <<PY
import keyring
keyring.set_password('openai','default','sk-ここにあなたのキー')
print('saved')
PY
```

2) Google Drive のサービスアカウント JSON（自動化向け）

ダウンロードした JSON を安全な場所に移動:

```bash
mkdir -p ~/.secrets
mv ~/Downloads/drive-service-account.json ~/.secrets/drive-sa.json
chmod 600 ~/.secrets/drive-sa.json
```

3) Gmail (notify_mail) のアプリパスワードを Keychain に保存（推奨）

```bash
python3 - <<PY
import keyring
keyring.set_password('gmail','furuta61@gmail.com','16桁のアプリパスワード')
print('saved')
PY
```

4) ドライラン（安全）

```bash
# events を GPT で評価するドライラン（Drive は service-account が必要）
python3 ~/Desktop/CFD3_AutoSystem/weekly_events_update.py --dry-run --file events.csv --service-account ~/.secrets/drive-sa.json

# IFD メールのドライラン
python3 ~/Desktop/CFD3_AutoSystem/notify_mail.py --dry-run
```

5) 本番送信（Gmail が Keychain に保存されていれば --send で実行）

```bash
python3 ~/Desktop/CFD3_AutoSystem/notify_mail.py --send --recipient you@domain.com
```

6) 注意点
- API キーや service-account.json をリポジトリやチャットに貼らないこと。
- launchd で定期実行する場合はユーザー LaunchAgent（~/Library/LaunchAgents）として Keychain アクセス可能な状態で動かしてください。

問題が発生したら、エラーメッセージをそのままここに貼ってください（秘密情報はマスクしてください）。
