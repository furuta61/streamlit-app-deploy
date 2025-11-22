#!/bin/bash
# CSVスクショシステム用のJSON生成
# GO以上の銘柄を自動出力

cd "$(dirname "$0")/.."

# .env 読み込み
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# デフォルト設定
export CAPITAL_JPY="${CAPITAL_JPY:-900000}"
export PER_LOT_JPY="${PER_LOT_JPY:-300000}"
export TRADE_MODE="${TRADE_MODE:-DAY6H}"

# 実行
./.venv/bin/python3 scripts/export_to_csv_screenshot.py \
    --threshold GO \
    --output output/csv_screenshot_orders.json

echo ""
echo "📄 Generated: output/csv_screenshot_orders.json"
echo "🔗 This JSON can be imported into your CSV screenshot automation system"
