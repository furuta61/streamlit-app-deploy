#!/bin/bash
cd "/Users/otomi/Desktop/vs code/CFD3_AutoSystem"
source .venv/bin/activate
source .env
nohup uvicorn server.webhook_server:app --port 8080 >/tmp/cfd3_uvicorn.log 2>&1 &
echo "Server started with PID: $!"
