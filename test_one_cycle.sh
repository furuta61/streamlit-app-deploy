#!/bin/bash
# test_one_cycle.sh
# 監視システムの1サイクルだけテスト実行

cd "$(dirname "$0")"

echo "🧪 24時間監視システム - 1サイクルテスト"
echo "================================================"
echo "注: 15分後に自動的に次のサイクルが始まりますが、"
echo "    最初の1サイクルだけ確認してCtrl+Cで停止してください。"
echo ""

./.venv/bin/python3 -c "
import sys
sys.path.insert(0, '.')
from continuous_monitor import monitoring_cycle, log_message

log_message('🧪 テストモード: 1サイクルのみ実行')
try:
    monitoring_cycle()
    log_message('✅ テスト完了')
except Exception as e:
    log_message(f'❌ エラー: {e}')
    import traceback
    traceback.print_exc()
"
