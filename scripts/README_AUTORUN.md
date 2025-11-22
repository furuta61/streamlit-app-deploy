# CFD3 Auto Run — 設定手順

このディレクトリには、毎週月曜 08:30 JST に `weekly_events_update.py` をプロジェクト venv 下で実行するためのサンプルが入っています。

作成ファイル一覧

- `scripts/run_weekly_ifd.sh` — 実行ラッパー（venv 有効化 → weekly_events_update.py を実行 → `logs/` に出力）
- `scripts/launchd/com.cfd3.weekly_ifd.plist` — macOS の `launchd` 用サンプル plist（`~/Library/LaunchAgents` にコピーして使用）

## 手順（launchd を使う場合、macOS ローカルユーザー）

1. 実行権限を付与

```zsh
chmod +x "/Users/otomi/Desktop/vs code/CFD3_AutoSystem/scripts/run_weekly_ifd.sh"
```

2. plist をユーザの LaunchAgents にコピーして読み込み

```zsh
mkdir -p ~/Library/LaunchAgents
cp "/Users/otomi/Desktop/vs code/CFD3_AutoSystem/scripts/launchd/com.cfd3.weekly_ifd.plist" ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.cfd3.weekly_ifd.plist
```

3. ログ確認（初回手動実行後、launchd 実行後）

```zsh
# 直近の実行ログを確認
ls -lt "/Users/otomi/Desktop/vs code/CFD3_AutoSystem/logs/" | head
# 標準出力 / 標準エラー
tail -n 200 "/Users/otomi/Desktop/vs code/CFD3_AutoSystem/logs/launchd_weekly_ifd.out.log"
tail -n 200 "/Users/otomi/Desktop/vs code/CFD3_AutoSystem/logs/launchd_weekly_ifd.err.log"
```

4. plist のアンロード（無効化）

```zsh
launchctl unload -w ~/Library/LaunchAgents/com.cfd3.weekly_ifd.plist
```

## 代替：crontab を使う場合（シンプル）

crontab に次の行を追加すると、毎週月曜 08:30 に実行されます（ローカルのタイムゾーンが JST 前提）。

```zsh
# crontab -e で追加
30 8 * * 1 /Users/otomi/Desktop/vs\ code/CFD3_AutoSystem/.venv/bin/python3 /Users/otomi/Desktop/vs\ code/CFD3_AutoSystem/weekly_events_update.py --local-file /Users/otomi/Desktop/vs\ code/CFD3_AutoSystem/scripts/events.csv --out /Users/otomi/Desktop/vs\ code/CFD3_AutoSystem/output --strict >> /Users/otomi/Desktop/vs\ code/CFD3_AutoSystem/logs/weekly_run.log 2>&1
```

注意：パスに空白があるため `\` エスケープまたは引用で囲む必要があります。launchd の方が macOS では推奨されます。

## 運用上の注意

- 初期は「提案（ファイル作成／メール通知）」のみ自動化し、数週間のモニタで安定性を確認してから自動発注へ移行してください。
- `weekly_events_update.py` が `market_data.csv` を参照する場合、market_data 更新ジョブを IFD ジョブより先に走らせる（例：同日 08:00 に market_data 更新 → 08:30 に IFD）
- 自動発注する場合は必ずロギングとメール通知を残し、失敗時にロールバックできる手順を準備してください。

---
必要なら、plist を `~/Library/LaunchAgents` に配置して自動で `launchctl load` して動作確認まで私が実行します（実行の可否を教えてください）。