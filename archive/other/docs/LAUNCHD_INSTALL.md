# CFD3_AutoSystem: launchd (macOS) 自動通知インストール手順

以下は macOS の `launchd` を使って、毎朝 08:00 にプロジェクト内の通知レポート（`app.notify_report`）を自動実行するための手順です。

前提
- リポジトリルートが `~/Desktop/vs code/CFD3_AutoSystem` にあること（あなたの環境に合わせてパスを読み替えてください）。
- 仮想環境が `./.venv` に作られており、`./.venv/bin/python3` が利用可能であること。
- 既に `scripts/run_notify.sh` と `launchd/com.cfd3.autonotify.plist` がワークスペースにあること。

手順（コマンドは zsh 用）

1) ラッパースクリプトを実行可能にする

```zsh
cd "/Users/otomi/Desktop/vs code/CFD3_AutoSystem"
chmod +x scripts/run_notify.sh
```

2) 環境変数（`.env`）を用意する（リポジトリルートに置く）

ファイル名: `.env`（ワークスペース直下）

サンプル内容（安全のためパスワードは環境に合わせて置き換えてください）:

```env
# SMTP (例: Gmail SMTP 用の app password)
ALERT_EMAIL_HOST=smtp.gmail.com
ALERT_EMAIL_PORT=465
ALERT_EMAIL_USER=you@example.com
ALERT_EMAIL_PASS=your_app_password_here
ALERT_EMAIL_TO=your@icloud.com

# オプション: Slack を使う場合
# SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
```

注意: Gmail を使う場合は「アプリパスワード」を使うか、適切な認証手段を設定してください。

3) venv に `certifi` を入れる（SSL 証明書検証対策）

```zsh
./.venv/bin/pip install certifi
```

4) launchd 用の plist をコピーして登録する

```zsh
# ユーの LaunchAgents ディレクトリにコピー
cp launchd/com.cfd3.autonotify.plist ~/Library/LaunchAgents/

# macOS に読み込ませる（ログイン中のユーザとして）
launchctl load ~/Library/LaunchAgents/com.cfd3.autonotify.plist

# 今すぐ起動したい場合
launchctl start com.cfd3.autonotify
```

5) ログ確認

launchd が実行するラッパーは標準出力/標準エラーを `~/Library/Logs/CFD3_AutoSystem/notify.log` に書く想定です。ファイルがなければ作成されます。

```zsh
tail -n +1 -F ~/Library/Logs/CFD3_AutoSystem/notify.log
```

6) 手動テスト

launchd に依存させる前に手動で実行して動作確認することをおすすめします：

```zsh
# リポジトリルートで
./.venv/bin/python3 -m app.notify_report

# またはラッパースクリプトを実行
./scripts/run_notify.sh
```

7) plist をアンロード/削除する場合

```zsh
launchctl unload ~/Library/LaunchAgents/com.cfd3.autonotify.plist
rm ~/Library/LaunchAgents/com.cfd3.autonotify.plist
```

トラブルシューティング

- SSL 証明書エラー（例: CERTIFICATE_VERIFY_FAILED）
  - 手早い対処: 仮想環境に `certifi` をインストールし、`app/notify_report.py` は `certifi.where()` を優先して SSLContext を作るようになっています。
  - それでも駄目な場合は、macOS の Python のための "Install Certificates.command" を実行するか（/Applications/Python 直下にある場合が多い）、システムキーチェーンの設定を確認してください。

- メール送信失敗
  - Gmail を使う場合は "アプリパスワード" を発行して `ALERT_EMAIL_PASS` に入れてください。2 段階認証が必要です。
  - `ALERT_EMAIL_HOST` / `ALERT_EMAIL_PORT` を間違えていないか確認してください（Gmail は通常 smtp.gmail.com:465）。

- launchd が動かない/起動しない
  - `launchctl load` のエラー出力を確認してください。plist の `ProgramArguments` が相対パスを参照している場合、ラッパーが正しいカレントディレクトリを設定しているか確認します（`scripts/run_notify.sh` はリポジトリルートで動く想定です）。
  - `launchctl list | grep com.cfd3.autonotify` でジョブが登録されているかを確認できます。

セキュリティ上の注意
- `.env` にパスワードを置く場合はファイルのアクセス権を制限してください：

```zsh
chmod 600 .env
```

- より安全にするなら macOS の Keychain 経由で秘密を取り扱う方法を検討してください（今後の改善項目）。

補足: 代替（テスト）
- launchd を使いたくない場合は `cron` や `launchd` の代替として `launchctl` での手動スケジュール、または GitHub Actions / CI を利用して定期実行することも可能です。

---
このファイルで不明点や追加して欲しい手順（例えば、Keychain 経由の秘密管理手順や systemd サービスファイル生成）などがあれば教えてください。