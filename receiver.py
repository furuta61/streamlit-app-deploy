"""
receiver.py
Webhook receiver for TradingView alerts.

See docs/pipeline_overview.md and docs/quick_start.md for setup and usage:
  - docs/pipeline_overview.md
  - docs/quick_start.md

This script listens on /webhook and appends incoming JSON to
`output/tradingview.jsonl` with flush+fsync to ensure immediate persistence.
"""
import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, abort

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'tradingview.jsonl')

app = Flask(__name__)


# =========================================================
# 🛡️ Token Validation Middleware
# =========================================================
@app.before_request
def verify_token():
    """
    TradingView Webhook Token Validation
    - TV_WEBHOOK_SECRET 環境変数に設定された値と一致しない場合 403 を返す
    - トークンはクエリパラメータ ?token= または HTTPヘッダー X-TV-Token から取得
    """
    expected_token = os.getenv("TV_WEBHOOK_SECRET", "")
    if not expected_token:
        return  # トークン未設定ならスキップ（開発・テスト用途）

    # クエリまたはヘッダーからトークン取得
    token = request.args.get("token") or request.headers.get("X-TV-Token")
    if token != expected_token:
        abort(403)


# =========================================================
# 🌐 Webhook 受信エンドポイント
# =========================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400

    if not data:
        return jsonify({"status": "error", "message": "Empty payload"}), 400

    # ログ出力
    print(f"📩 Received: {data}", flush=True)

    # データをファイルに追記
    try:
        with open(OUTPUT_FILE, "a") as f:
            f.write(json.dumps({
                "timestamp": datetime.utcnow().isoformat(),
                "data": data
            }) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"⚠️ Write Error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "ok"}), 200


# =========================================================
# 🚀 アプリ起動
# =========================================================
if __name__ == '__main__':
    print("✅ Receiver server starting at http://127.0.0.1:8000 ...")
    app.run(host='0.0.0.0', port=8000)
