#!/usr/bin/env python3
"""
Simple TradingView webhook receiver for local testing.

Receives POST JSON from TradingView alerts and appends them to
`output/tradingview.jsonl` as newline-delimited JSON records.

Usage (dev):
  # install Flask in your venv: pip install flask
  FLASK_APP=tools/tv_webhook_listener.py flask run --port 5001

Expose via ngrok to receive tradingview webhooks from TradingView.
"""
import os
import time
import json
from flask import Flask, request, abort

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUT_PATH = os.path.join(OUTPUT_DIR, 'tradingview.jsonl')

app = Flask(__name__)

# Simple token auth: set TV_WEBHOOK_SECRET in environment and include ?token=SECRET
TV_WEBHOOK_SECRET = os.getenv('TV_WEBHOOK_SECRET')


@app.route('/tv-webhook', methods=['POST'])
def tv_webhook():
    # Basic JSON receiver. TradingView can POST arbitrary text; try to parse JSON.
    # Verify token if configured
    if TV_WEBHOOK_SECRET:
        req_token = request.args.get('token') or request.headers.get('X-TV-Token')
        if not req_token or req_token != TV_WEBHOOK_SECRET:
            abort(403)

    try:
        payload = request.get_json(force=True)
    except Exception:
        # if not JSON, try raw text
        try:
            text = request.get_data(as_text=True)
            payload = {'text': text}
        except Exception:
            abort(400)

    entry = {
        'ts': time.time(),
        'remote_addr': request.remote_addr,
        'headers': {k: v for k, v in request.headers.items()},
        'payload': payload
    }
    try:
        with open(OUT_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass
    return ('', 204)


if __name__ == '__main__':
    # debug server for local testing
    app.run(host='0.0.0.0', port=int(os.getenv('TV_WEBHOOK_PORT', '5001')), debug=False)
