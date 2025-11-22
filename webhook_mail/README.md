# webhook_mail — lightweight webhook → Gmail bridge

Purpose
- Small FastAPI app that receives JSON webhooks and forwards them as plain-text Gmail messages.

Setup
1. Copy `.env.example` to `.env` and fill in GMAIL_USER, GMAIL_APP_PASSWORD, GMAIL_TO, and optionally WEBHOOK_TOKEN.
2. Create a virtualenv and install dependencies from `webhook_mail/requirements.txt`.

Example
```
python -m venv .venv
source .venv/bin/activate
pip install -r webhook_mail/requirements.txt
cp .env.example .env
# edit .env with real values
uvicorn webhook_mail.main:app --host 0.0.0.0 --port 8000
```

Testing
- Send a POST with JSON body and header `X-Webhook-Token` (if set):

```
curl -X POST http://localhost:8000/webhook -H "Content-Type: application/json" -H "X-Webhook-Token: changeme_token" -d '{"symbol":"XAUUSD","signal":"STRONG_GO","text":"Test"}'
```

Security
- Use a non-empty `WEBHOOK_TOKEN` and set it both in your TradingView webhook and `.env`.
- For Gmail, prefer an App Password and do not commit .env to source control.
