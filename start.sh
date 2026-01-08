#!/usr/bin/env bash

# FastAPIバックエンドをバックグラウンドで起動
uvicorn quiz_pack.backend.main:app --host 0.0.0.0 --port 8002 &

# 少し待ってからStreamlitを起動
sleep 3
streamlit run quiz_pack/app_tabs_final.py --server.port $PORT --server.address 0.0.0.0
