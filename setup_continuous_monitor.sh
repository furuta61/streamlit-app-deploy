#!/bin/bash
# setup_continuous_monitor.sh
# 24時間監視システムのセットアップと管理スクリプト

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PLIST_SOURCE="${SCRIPT_DIR}/launchd/cfd3_autosystem.continuous.plist"
PLIST_DEST="${HOME}/Library/LaunchAgents/cfd3_autosystem.continuous.plist"
SERVICE_NAME="com.cfd3.autosystem.continuous"

echo "🚀 CFD3 24時間監視システム セットアップ"
echo "================================================"

# 引数チェック
if [ $# -eq 0 ]; then
    echo "使用方法:"
    echo "  $0 install   - システムに登録して自動起動を有効化"
    echo "  $0 start     - 監視システムを開始"
    echo "  $0 stop      - 監視システムを停止"
    echo "  $0 restart   - 監視システムを再起動"
    echo "  $0 status    - 監視システムの状態を確認"
    echo "  $0 uninstall - システムから削除"
    echo "  $0 logs      - ログをリアルタイム表示"
    echo "  $0 test      - 手動でテスト実行（フォアグラウンド）"
    exit 0
fi

COMMAND=$1

case $COMMAND in
    install)
        echo "📦 インストール中..."
        
        # LaunchAgentsディレクトリ作成
        mkdir -p "${HOME}/Library/LaunchAgents"
        
        # config ディレクトリ作成とデフォルト env
        mkdir -p "${SCRIPT_DIR}/config"
        if [ ! -f "${SCRIPT_DIR}/config/high_accuracy.env" ]; then
            echo "USE_HIGH_ACCURACY=0" > "${SCRIPT_DIR}/config/high_accuracy.env"
            chmod 600 "${SCRIPT_DIR}/config/high_accuracy.env"
            echo "✅ デフォルト設定を作成: ${SCRIPT_DIR}/config/high_accuracy.env"
        fi

        # Ensure wrapper is executable
        if [ -f "${SCRIPT_DIR}/bin/run_continuous_monitor.sh" ]; then
            chmod +x "${SCRIPT_DIR}/bin/run_continuous_monitor.sh" || true
        fi

        # plistファイルをコピー
        cp "$PLIST_SOURCE" "$PLIST_DEST"
        echo "✅ plistファイルをコピー: $PLIST_DEST"
        
        # launchd に登録 (unload/load で再読み込みを確実に行う)
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
        launchctl load "$PLIST_DEST"
        echo "✅ launchdに登録完了"
        
        # ログディレクトリ作成
        mkdir -p "${SCRIPT_DIR}/logs"
        
        echo ""
        echo "🎉 インストール完了！"
        echo "システム起動時に自動的に監視が開始されます。"
        echo ""
        echo "📋 次のステップ:"
        echo "1. Gmail通知設定を確認:"
        echo "   cd '$SCRIPT_DIR' && ./.venv/bin/python3 -c \"import yagmail; yagmail.register('furuta61@gmail.com', 'アプリパスワード')\""
        echo ""
        echo "2. ステータス確認:"
        echo "   $0 status"
        echo ""
        echo "3. ログ確認:"
        echo "   $0 logs"
        ;;
    
    start)
        echo "▶️ 監視システムを開始..."
        launchctl start "$SERVICE_NAME"
        sleep 2
        launchctl list | grep "$SERVICE_NAME" || echo "⚠️ サービスが見つかりません"
        echo "✅ 開始コマンド実行完了"
        echo "ステータス確認: $0 status"
        ;;
    
    stop)
        echo "⏹️ 監視システムを停止..."
        launchctl stop "$SERVICE_NAME"
        echo "✅ 停止コマンド実行完了"
        ;;
    
    restart)
        echo "🔄 監視システムを再起動..."
        # Use unload/load to ensure new env and ProgramArguments are picked up
        if [ -f "$PLIST_DEST" ]; then
            launchctl unload "$PLIST_DEST" 2>/dev/null || true
            sleep 1
            launchctl load "$PLIST_DEST"
            sleep 2
            launchctl list | grep "$SERVICE_NAME" || true
            echo "✅ 再起動完了 (unload/load)"
        else
            echo "⚠️ plist が見つかりません: $PLIST_DEST. 試しに start/stop を行います。"
            launchctl stop "$SERVICE_NAME" 2>/dev/null || true
            sleep 2
            launchctl start "$SERVICE_NAME"
            sleep 2
            launchctl list | grep "$SERVICE_NAME" || true
            echo "✅ 再起動完了 (start/stop fallback)"
        fi
        ;;
    
    status)
        echo "📊 監視システムの状態:"
        echo "================================================"
        
        if launchctl list | grep -q "$SERVICE_NAME"; then
            echo "✅ サービス: 実行中"
            launchctl list | grep "$SERVICE_NAME"
        else
            echo "⚠️ サービス: 停止中または未登録"
        fi
        
        echo ""
        echo "📄 最新ログ（最後の20行）:"
        echo "================================================"
        LOG_FILE="${SCRIPT_DIR}/logs/continuous_monitor.out"
        if [ -f "$LOG_FILE" ]; then
            tail -n 20 "$LOG_FILE"
        else
            echo "ログファイルがまだ作成されていません"
        fi
        ;;
    
    uninstall)
        echo "🗑️ アンインストール中..."
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
        rm -f "$PLIST_DEST"
        echo "✅ plist を削除しました: $PLIST_DEST"
        # config は削除せず残す（設定保護）。必要なら手動で削除してください。
        echo "✅ アンインストール完了"
        echo "注: ログファイルは削除されていません（手動で削除してください）"
        ;;
    
    logs)
        echo "📜 ログをリアルタイム表示（Ctrl+Cで終了）"
        echo "================================================"
        LOG_FILE="${SCRIPT_DIR}/logs/continuous_monitor.out"
        if [ -f "$LOG_FILE" ]; then
            tail -f "$LOG_FILE"
        else
            echo "⚠️ ログファイルがまだ作成されていません"
            exit 1
        fi
        ;;
    
    test)
        echo "🧪 テスト実行（フォアグラウンド、Ctrl+Cで終了）"
        echo "================================================"
        cd "$SCRIPT_DIR"
        ./.venv/bin/python3 continuous_monitor.py
        ;;
    
    *)
        echo "❌ 不明なコマンド: $COMMAND"
        echo "使用方法: $0 {install|start|stop|restart|status|uninstall|logs|test}"
        exit 1
        ;;
esac
