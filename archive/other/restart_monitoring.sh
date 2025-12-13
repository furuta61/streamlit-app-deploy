#!/bin/bash
# システム再起動スクリプト (Gmail制限解除後に実行)

echo "🚀 CFD3監視システム再起動"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. Gmail送信テスト
echo "📧 Step 1: Gmail送信テスト..."
cd '/Users/otomi/Desktop/vs code/CFD3_AutoSystem'
./.venv/bin/python3 -c "
import yagmail
try:
    yag = yagmail.SMTP('furuta61@gmail.com')
    yag.send('furuta61@gmail.com', 
             '【テスト】CFD3システム再起動', 
             'Gmail送信制限が解除されました。システムを再起動します。')
    print('✅ Gmail送信成功')
except Exception as e:
    print(f'❌ Gmail送信失敗: {e}')
    print('⚠️ まだ制限中の可能性があります')
    exit(1)
"

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Gmail制限がまだ解除されていません"
    echo "💡 数時間後に再度実行してください"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Step 2: 連続監視システム起動..."
echo ""

# 2. launchdサービス起動
launchctl load ~/Library/LaunchAgents/com.cfd3.autosystem.plist 2>/dev/null
sleep 2

# 3. 状態確認
echo "📋 システム状態:"
launchctl list | grep cfd3

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ システム再起動完了"
echo ""
echo "📌 重要:"
echo "  - 30秒ごとに6銘柄のトレンドを監視"
echo "  - トレンド反転時はGmail通知"
echo "  - 重複防止: 同じ反転は1時間に1回のみ通知"
echo ""
echo "📊 ログ確認:"
echo "  tail -f logs/continuous_monitor.out"
echo ""
