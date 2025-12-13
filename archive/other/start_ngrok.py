#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start_ngrok.py
ローカル FastAPI サーバ (port=8080) を ngrok 経由で公開し、URL を表示します。

使い方:
  1) requirements.txt に pyngrok を追加し `pip install -r requirements.txt`
  2) NGROK_AUTHTOKEN を環境変数に設定 (初回のみ)
       export NGROK_AUTHTOKEN="xxxxxxxxxxxxxxxx"
  3) サーバ起動 (別ターミナル):
       uvicorn webhook_server:app --port 8080
  4) 本スクリプトを実行:
       python start_ngrok.py

終了方法:
  Ctrl+C でトンネルを閉じます。
"""
from __future__ import annotations
import os
import time
from pyngrok import ngrok

PORT = 8080

authtoken = os.environ.get("NGROK_AUTHTOKEN")
if not authtoken:
    print("[ERROR] NGROK_AUTHTOKEN が設定されていません。https://dashboard.ngrok.com/get-started/your-authtoken を参照して取得し、環境変数に設定してください。")
    raise SystemExit(1)

# 既存トンネルを全て閉じる（再起動対策）
for t in ngrok.get_tunnels():
    ngrok.disconnect(t.public_url)

# 認証設定
ngrok.set_auth_token(authtoken)

print(f"[INFO] ngrok トンネルを起動します (localhost:{PORT}) ...")
public_url = ngrok.connect(addr=PORT, proto="http")
print("[INFO] 公開URL:")
print(f"  {public_url.public_url}")
print("[INFO] 例: TradingView Webhook の URL は →", f"{public_url.public_url}/webhook")
print("[INFO] CTRL+C で終了します。ログ待受中...")

try:
    while True:
        time.sleep(5)
except KeyboardInterrupt:
    print("\n[INFO] ngrok トンネルを閉じます...")
    ngrok.kill()
    print("[INFO] 終了しました。")
