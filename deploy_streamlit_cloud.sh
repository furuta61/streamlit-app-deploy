#!/usr/bin/env bash
# シンプル自動確認スクリプト: Streamlit Cloud へ push する前のチェック
set -euo pipefail

echo "[1/5] Python venv 確認"
if [ ! -d .venv ]; then
  echo "  .venv がありません。 python3 -m venv .venv を実行してください"; fi

echo "[2/5] 必須ファイル存在確認"
for f in webhook_mail/streamlit_app.py webhook_mail/main.py README.md requirements.txt; do
  [ -f "$f" ] || { echo "  MISSING: $f"; exit 1; }; done

echo "[3/5] API_URL 動的化確認"
if ! grep -q 'PUBLIC_BASE_URL' webhook_mail/streamlit_app.py; then
  echo "  PUBLIC_BASE_URL 未対応: streamlit_app.py 修正が必要"; exit 1; fi

echo "[4/5] Git 変更一覧"
git status --short || true

echo "[5/5] 推奨コミット"
echo "  git add webhook_mail/streamlit_app.py README.md"
echo "  git commit -m 'deploy: Streamlit Cloud 上書き用更新'"
echo "  git push origin master"

echo "完了: 上記 push 後に Streamlit Cloud が自動再デプロイします。"
