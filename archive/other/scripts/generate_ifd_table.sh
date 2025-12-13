#!/bin/bash
# -*- coding: utf-8 -*-
#
# scripts/generate_ifd_table.sh
# 
# 実際の市場価格とニュースを使ってIFD注文テーブルを生成します
# レーティング順（おすすめ順）に売買方向付きで表示
#
# 使い方: ./scripts/generate_ifd_table.sh

set -e

# スクリプトのディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# .env ファイルを読み込み
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Python実行
./.venv/bin/python3 -c "from mygpt_strategy import generate_ifd; exec(open('scripts/show_ifd_table.py').read())"
