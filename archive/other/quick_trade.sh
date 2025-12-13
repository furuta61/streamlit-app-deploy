#!/usr/bin/env bash
# quick_trade.sh
# ワンコマンドでトレード準備完了 + Gmail通知

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

echo "🚀 クイックトレード開始..."
echo ""

# 1. 最新の市場データを取得してIFD注文を生成
echo "📈 Step 1/3: 最新データ取得 & IFD生成..."
./.venv/bin/python3 realtime_ifd_run.py

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 2. トレード可能なシグナルを見やすく表示
echo "📊 Step 2/3: トレード実行用表示..."
./.venv/bin/python3 show_ifd_latest.py

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 3. Gmail通知を送信（STRONG_GOまたはGOがある場合のみ）
echo "📧 Step 3/3: Gmail通知送信..."

# 最新ファイルから STRONG_GO または GO があるかチェック
LATEST_FILE=$(ls -t output/events_scored_*.csv 2>/dev/null | head -1)

if [ -z "$LATEST_FILE" ]; then
    # Google Driveから最新ファイルをコピー
    DRIVE_FILE=$(ls -t "/Users/otomi/Google ドライブ/CFD3Pro/events_scored_"*.csv 2>/dev/null | head -1)
    if [ -n "$DRIVE_FILE" ]; then
        cp "$DRIVE_FILE" output/
        LATEST_FILE=$(ls -t output/events_scored_*.csv 2>/dev/null | head -1)
    fi
fi

if [ -n "$LATEST_FILE" ]; then
    # STRONG_GO または GO があるかチェック（lot_size > 0）
    TRADABLE_COUNT=$(awk -F',' 'NR>1 && $9+0>0 {count++} END {print count+0}' "$LATEST_FILE")
    
    if [ "$TRADABLE_COUNT" -gt 0 ]; then
        echo "✅ トレード可能なシグナル: ${TRADABLE_COUNT}件"
        
        # メール本文を生成
        EMAIL_BODY="$(cat << EOF
🎯 CFD3 AutoSystem - トレードシグナル通知

📊 トレード可能なシグナル: ${TRADABLE_COUNT}件

最新のIFD注文が生成されました。
詳細は添付ファイルまたは以下を確認してください：

${LATEST_FILE}

🚀 次のステップ:
1. GMOクリック証券にログイン
2. IFD注文を設定
3. 経済指標発表を待つ

⏰ 生成時刻: $(date '+%Y-%m-%d %H:%M:%S')
EOF
)"
        
        # Gmailに送信（環境変数でメールアドレスを設定）
        RECIPIENT="${EMAIL_USER:-furuta61@gmail.com}"
        
        ./.venv/bin/python3 -c "
import yagmail
import os
import sys

try:
    # Keychainから認証情報を取得
    yag = yagmail.SMTP('furuta61@gmail.com')
    
    subject = '[CFD3] 🎯 トレードシグナル通知 - ${TRADABLE_COUNT}件'
    body = '''$EMAIL_BODY'''
    
    yag.send(
        to='$RECIPIENT',
        subject=subject,
        contents=body,
        attachments='$LATEST_FILE'
    )
    print('📧 Gmail送信成功: $RECIPIENT')
except Exception as e:
    print(f'⚠️ Gmail送信失敗: {e}')
    print('💡 Keychainに認証情報を登録してください：')
    print('   python3 -c \"import yagmail; yagmail.register(\\\"furuta61@gmail.com\\\", \\\"アプリパスワード\\\")\"')
    sys.exit(1)
"
    else
        echo "ℹ️ トレード可能なシグナルなし（全てロット0）"
    fi
else
    echo "⚠️ 結果ファイルが見つかりません"
fi

echo ""
echo "✅ 完了！上記の情報を使ってトレードを実行してください。"
