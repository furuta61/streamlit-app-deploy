from fastapi import FastAPI, Request, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import json
from datetime import datetime
import smtplib
import time
import requests
from email.message import EmailMessage
from email.utils import make_msgid
import io
import contextlib
import logging
import subprocess
import sys
from pathlib import Path
import shutil
import pandas as pd
from typing import Optional
import base64
import re
from PIL import Image, ImageEnhance, ImageFilter
# --- OpenAI クライアント（最新仕様） ---
from openai import OpenAI
client = OpenAI()
try:
    from googleapiclient.discovery import build
    from google.oauth2 import service_account
    SHEETS_AVAILABLE = True
except Exception:
    SHEETS_AVAILABLE = False

load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
GMAIL_TO = os.getenv("GMAIL_TO", "")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")

# Webhook CSV / IFD settings
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
# If true ("1"/"true") then run the portfolio script after writing CSV
RUN_IFD_ON_WEBHOOK = os.getenv("RUN_IFD_ON_WEBHOOK", "false").lower() in ("1", "true", "yes")
# IFD run mode: strict_4h (default), closed_60m (run on every closed 60m/240m bar),
# always (run on every closed bar regardless of frame), manual (never auto-run here)
IFD_RUN_MODE = os.getenv("IFD_RUN_MODE", "strict_4h").lower()

# Optional: gate IFD auto-run to specific local times (e.g., "09:15,13:15,17:15,22:30")
IFD_SCHEDULE_WINDOWS = os.getenv("IFD_SCHEDULE_WINDOWS", "")
# Timezone for schedule windows (e.g., Asia/Tokyo)
IFD_SCHEDULE_TZ = os.getenv("IFD_SCHEDULE_TZ", "Asia/Tokyo")
# Minutes tolerance around scheduled times to allow a run (e.g., 5-10 min window)
try:
    IFD_SCHEDULE_TOLERANCE_MIN = int(os.getenv("IFD_SCHEDULE_TOLERANCE_MIN", "7"))
except Exception:
    IFD_SCHEDULE_TOLERANCE_MIN = 7
# Schedule policy: gate (enforce windows), prefer (do not block outside windows), off (ignore windows)
IFD_SCHEDULE_POLICY = os.getenv("IFD_SCHEDULE_POLICY", "gate").lower()
# Analysis timeframe to pass to IFD generator: '4h' (default) | '1h' | '30m'
IFD_TIMEFRAME = os.getenv("IFD_TIMEFRAME", "4h")

def _parse_schedule_windows(s: str) -> list[tuple[int, int]]:
    """Parse a comma-separated list of HH:MM into [(hour, minute), ...]."""
    out: list[tuple[int, int]] = []
    try:
        for tok in (s or "").split(","):
            tok = tok.strip()
            if not tok:
                continue
            if ":" not in tok:
                continue
            hh, mm = tok.split(":", 1)
            try:
                h = int(hh) % 24
                m = int(mm) % 60
                out.append((h, m))
            except Exception:
                continue
    except Exception:
        pass
    return out

SCHEDULE_WINDOWS = _parse_schedule_windows(IFD_SCHEDULE_WINDOWS)

app = FastAPI(title="CFD3_AutoSystem", version="2.3.0")
START_TIME = time.time()

logger = logging.getLogger("webhook_mail")
logging.basicConfig(level=logging.INFO)
logger.info("webhook_mail DATA_DIR=%s RUN_IFD_ON_WEBHOOK=%s IFD_RUN_MODE=%s", DATA_DIR, RUN_IFD_ON_WEBHOOK, IFD_RUN_MODE)
if SCHEDULE_WINDOWS:
    logger.info("IFD schedule windows (tz=%s, tol=%s min, policy=%s): %s", IFD_SCHEDULE_TZ, IFD_SCHEDULE_TOLERANCE_MIN, IFD_SCHEDULE_POLICY, IFD_SCHEDULE_WINDOWS)
else:
    logger.info("IFD schedule windows disabled (policy=%s)", IFD_SCHEDULE_POLICY)

# Which signals should trigger an email. Comma-separated, default: STRONG_GO
NOTIFY_ON = [s.strip().upper() for s in os.getenv("NOTIFY_ON", "STRONG_GO").split(",") if s.strip()]
logger.info("notify_on=%s", NOTIFY_ON)

# Keywords to scan in freeform text when explicit `signal` is missing or doesn't match.
# Includes common English tokens and likely Japanese tokens like '交差'.
TEXT_KEYWORDS = [k.lower() for k in os.getenv("NOTIFY_TEXT_KEYWORDS", "STRONG_GO,GO,cross,交差,IFD").split(",") if k.strip()]
logger.info("notify_text_keywords=%s", TEXT_KEYWORDS)

# --- Optional OCR (pytesseract) import for Streamlit Cloud compatibility ---
try:
    import pytesseract  # type: ignore
except ModuleNotFoundError:
    pytesseract = None  # type: ignore
    print("⚠️ pytesseract が見つかりません (Streamlit Cloud 環境)。Vision OCR のみを使用します。")
try:
    from webhook_mail.opencv_preprocess import preprocess_image as opencv_preprocess_image  # type: ignore
    OPENCV_AVAILABLE = True
except Exception:
    OPENCV_AVAILABLE = False


# --- Google Sheets 連携（オプション） ---
def write_to_sheets(record: dict):
    """Google Sheetsに1行追加（未設定や未インストールなら黙ってスキップ）。

    必要な環境変数:
    - GOOGLE_CREDENTIALS_JSON: サービスアカウントJSONの全文
    - SHEET_ID: スプレッドシートID
    """
    if not SHEETS_AVAILABLE:
        logger.info("Sheets library not installed; skip logging")
        return
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    sheet_id = os.getenv("SHEET_ID")
    if not creds_json or not sheet_id:
        logger.info("Sheets not configured (GOOGLE_CREDENTIALS_JSON / SHEET_ID missing); skip logging")
        return

    try:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(creds_json),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=creds)
        # record の key 順序は dict 依存なので、ここでは安定列を定義
        ordered_keys = [
            "timestamp","symbol","direction","entry","tp","sl","signal","confidence","comment"
        ]
        row = [record.get(k, "") for k in ordered_keys]
        body = {"values": [row]}
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="Logs!A1",
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()
        logger.info("✅ Google Sheets に記録: %s", record)
    except Exception:
        logger.exception("Failed to write to Google Sheets")


@app.get("/health")
async def health_check():
    """包括的ヘルスチェック (v2.3.0 / OpenCV可視化対応)"""
    uptime = round(time.time() - START_TIME, 2)
    server_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # OpenAI / Vision 状態（APIキー存在のみで簡易活性表示）
    api_key = os.getenv("OPENAI_API_KEY")
    vision_status = "active" if api_key else "no_api_key"

    # Sheets設定確認
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    sheet_id = os.getenv("SHEET_ID")
    try:
        if creds_json and sheet_id:
            json.loads(creds_json)
            sheets_status = "configured"
        else:
            sheets_status = "missing"
    except Exception:
        sheets_status = "invalid_credentials_json"

    # Tesseract状態
    try:
        tess_path = shutil.which("tesseract")
        if tess_path:
            proc = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, timeout=5)
            tesseract_status = "installed" if proc.returncode == 0 else f"error:{proc.returncode}"
        else:
            tesseract_status = "missing"
    except Exception as e:
        tesseract_status = f"error:{e}"

    # OpenCV状態
    import importlib.util
    opencv_available = importlib.util.find_spec("cv2") is not None

    return {
        "status": "ok",
        "version": "2.3.0",
        "uptime_sec": uptime,
        "server_time": server_time,
        "vision_status": vision_status,
        "sheets_status": sheets_status,
        "tesseract": tesseract_status,
        "opencv": "available" if opencv_available else "missing",
        "message": "CFD3_AutoSystem v2.3 稼働中 🚀"
    }


@app.get("/health/page", response_class=HTMLResponse)
async def health_page():
    """人間がブラウザで確認しやすいHTMLステータスページ。

    プログラムからの監視用途は従来の /health (JSON) を継続利用可能。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode = 'Direct' if not os.getenv('PUBLIC_BASE_URL') else f"API ({os.getenv('PUBLIC_BASE_URL')})"
    api_key_present = bool(os.getenv('OPENAI_API_KEY'))
    # Sheets config status (lightweight check)
    try:
        creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
        sheet_id = os.getenv('SHEET_ID')
        if creds_json and sheet_id:
            try:
                json.loads(creds_json)
                sheets_status = "configured"
            except Exception:
                sheets_status = "invalid_credentials_json"
        else:
            sheets_status = "missing"
    except Exception:
        sheets_status = "error"
    # Detect Tesseract status quickly for page display
    try:
        tesseract_status = "installed" if shutil.which("tesseract") else "missing"
    except Exception:
        tesseract_status = "unknown"

    html = f"""
    <html>
        <head>
            <title>🩺 System Health Check</title>
            <meta charset="utf-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Arial'; background-color: #f7f9fc; color: #333; padding: 1.8em; line-height: 1.5; }}
                h1 {{ color: #0078d7; margin-top: 0; }}
                .ok {{ color: #0d7d28; font-weight: bold; }}
                .fail {{ color: #c40000; font-weight: bold; }}
                .grid {{ display: grid; grid-template-columns: 160px 1fr; gap: 0.4em 1.2em; max-width: 780px; background:#fff; padding:1.2em 1.4em; border-radius:12px; box-shadow:0 2px 6px rgba(0,0,0,0.08); }}
                .label {{ font-weight:600; }}
                footer {{ margin-top:2.0em; font-size:12px; opacity:0.7; }}
                a {{ color:#0078d7; text-decoration:none; }}
                a:hover {{ text-decoration:underline; }}
            </style>
        </head>
        <body>
            <h1>🩺 CFD3_AutoSystem Health Status</h1>
            <div class="grid">
                <div class="label">Status</div><div><span class="ok">OK</span></div>
                <div class="label">Mode</div><div>{mode}</div>
                <div class="label">Version</div><div>{app.version}</div>
                <div class="label">OpenAI API Key</div><div>{'✅ Detected' if api_key_present else '<span class="fail">❌ Missing</span>'}</div>
                <div class="label">Vision Model</div><div>gpt-4o</div>
                <div class="label">IFD Module</div><div>✅ Connected</div>
                <div class="label">Sheets</div><div>{sheets_status}</div>
                <div class="label">Tesseract</div><div>{tesseract_status}</div>
                <div class="label">Last Checked</div><div>{now}</div>
            </div>
            <footer>
                FastAPI JSON endpoint: <code>/health</code> | HTML page: <code>/health/page</code><br>
                Uvicorn worker active. For monitoring, prefer the JSON endpoint for automation.
            </footer>
        </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)


# Raw webhook persistence for debugging
RAW_LOG = os.path.join(os.path.dirname(__file__), '..', 'output', 'tradingview_raw.log')
NOTIFY_EVAL_LOG = os.path.join(os.path.dirname(__file__), '..', 'logs', 'notify_eval.log')
SMTP_LOG = os.path.join(os.path.dirname(__file__), '..', 'logs', 'notify_smtp.log')


class WebhookPayload(BaseModel):
    symbol: str | None = None
    signal: str | None = None
    text: str | None = None
    data: dict | None = None
    timeframe: Optional[str] = None
    # tradingview-like bar state, e.g. 'closed' when bar finished
    barstate: Optional[str] = None
    is_realtime: Optional[bool] = None
    # optional flat ohlc fields
    time: Optional[str] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None


class IfdRunRequest(BaseModel):
    symbols: Optional[str] = None  # comma-separated (e.g., "JP225,NAS100,XAUUSD")
    single: Optional[bool] = True
    expiry_hours: Optional[int] = 4
    trade_mode: Optional[str] = None
    data_dir: Optional[str] = None  # override DATA_DIR if needed
    # raw passthrough of --only; used if symbols is not set
    only: Optional[str] = None
    # timeframe: '4h' | '1h' | '30m'
    tf: Optional[str] = None
def _extract_signal(payload: WebhookPayload) -> tuple[str, str]:
    """Try to extract a decisive signal name (uppercased) from various fields.

    Returns (signal_upper, source)
    source is a hint like 'payload.signal', 'data.signal', 'text', etc.
    """
    try:
        if payload.signal:
            s = str(payload.signal).strip().upper()
            if s:
                return s, 'payload.signal'
    except Exception:
        pass

    # search data dict
    d = payload.data or {}
    if isinstance(d, dict):
        candidates = [
            'signal', 'sig', 'decision', 'alert', 'alert_name', 'type',
            'message', 'alert_message', 'note', 'comment', 'strategy',
            'strategy_order_comment', 'labels', 'label', 'condition'
        ]
        # direct keys
        for k in candidates:
            try:
                if k in d and isinstance(d[k], str):
                    s = d[k].strip().upper()
                    if s:
                        return s, f'data.{k}'
            except Exception:
                continue
        # nested strategy/order comments
        try:
            strat = d.get('strategy') or {}
            if isinstance(strat, dict):
                for k in ('order', 'comment', 'order_comment'):
                    v = strat.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip().upper(), 'data.strategy.' + k
        except Exception:
            pass

    # parse free text for tokens like STRONG_GO
    try:
        text = (payload.text or '')
        # simple scan for strong_go like tokens
        tokens = [
            'STRONG_GO', 'STRONG-GO', 'STRONG GO',
            'GO', 'STRONG_SELL', 'STRONG_BUY'
        ]
        tl = text.upper()
        for tok in tokens:
            if tok in tl:
                # normalize to underscore style
                norm = tok.replace(' ', '_').replace('-', '_')
                return norm, 'text'
    except Exception:
        pass

    # last resort: scan flattened JSON
    try:
        dump = json.dumps(payload.data or {}).upper()
        for tok in ('STRONG_GO', 'STRONG-GO', 'STRONG GO', 'GO'):
            if tok in dump:
                norm = tok.replace(' ', '_').replace('-', '_')
                return norm, 'data_dump'
    except Exception:
        pass

    return '', ''

def _evaluate_notification(payload: WebhookPayload, request: Request) -> dict:
    """Evaluate whether to notify, with detailed reasoning and header overrides.

    Header overrides:
    - X-Notify-Force: 1/true/yes => force notify
    - X-Notify-On: comma list of signals to match (overrides env NOTIFY_ON)
    - X-Notify-Keywords: comma list of extra text keywords (added to env keywords)
    """
    force = False
    try:
        force = (request.headers.get('X-Notify-Force', '').lower() in ('1','true','yes'))
    except Exception:
        pass

    # base config
    on_list = list(NOTIFY_ON)
    extra_on = (request.headers.get('X-Notify-On', '') or '')
    if extra_on:
        try:
            on_list = [s.strip().upper() for s in extra_on.split(',') if s.strip()]
        except Exception:
            pass

    keywords = list(TEXT_KEYWORDS)
    extra_kw = (request.headers.get('X-Notify-Keywords', '') or '')
    if extra_kw:
        try:
            keywords += [k.strip().lower() for k in extra_kw.split(',') if k.strip()]
        except Exception:
            pass

    detail = {
        'force': force,
        'notify_on': on_list,
        'keywords': keywords,
        'matched': False,
        'reason': '',
        'extracted_signal': '',
        'extracted_source': '',
        'matched_keyword': ''
    }

    if force:
        detail['matched'] = True
        detail['reason'] = 'forced'
        return detail

    # ALL wildcard
    try:
        if any(x in on_list for x in ('*','ALL')):
            detail['matched'] = True
            detail['reason'] = 'notify_on_all'
            return detail
    except Exception:
        pass

    # extract signal
    sig, src = _extract_signal(payload)
    detail['extracted_signal'] = sig
    detail['extracted_source'] = src
    if sig and sig in on_list:
        detail['matched'] = True
        detail['reason'] = f'signal_match({src})'
        return detail

    # text search
    text = (payload.text or '').lower()
    for kw in keywords:
        try:
            if kw and kw in text:
                detail['matched'] = True
                detail['reason'] = 'text_keyword'
                detail['matched_keyword'] = kw
                return detail
        except Exception:
            continue

    # data values search
    d = payload.data or {}
    if isinstance(d, dict):
        for v in d.values():
            try:
                if isinstance(v, str):
                    lv = v.lower()
                    for kw in keywords:
                        try:
                            if kw and kw in lv:
                                detail['matched'] = True
                                detail['reason'] = 'data_keyword'
                                detail['matched_keyword'] = kw
                                return detail
                        except Exception:
                            continue
            except Exception:
                continue

    # flattened dump search
    try:
        dump = json.dumps(payload.data or {}).lower()
        for kw in keywords:
            if kw and kw in dump:
                detail['matched'] = True
                detail['reason'] = 'dump_keyword'
                detail['matched_keyword'] = kw
                return detail
    except Exception:
        pass

    detail['reason'] = 'no_match'
    return detail


def send_email(subject: str, body: str, to_addrs: str):
    """Send a simple plain-text email via Gmail SMTP (SSL).

    to_addrs: comma-separated string of recipients
    """
    # Allow fallback to ALERT_EMAIL_* environment variables (existing repo .env)
    smtp_user = GMAIL_USER or os.getenv("ALERT_EMAIL_USER")
    smtp_pass = GMAIL_APP_PASSWORD or os.getenv("ALERT_EMAIL_PASS")
    smtp_host = os.getenv("ALERT_EMAIL_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("ALERT_EMAIL_PORT", "465"))

    recipients = to_addrs or os.getenv("ALERT_EMAIL_TO", "")

    if not smtp_user or not smtp_pass or not recipients:
        raise RuntimeError("メール設定が不完全です。 .env (GMAIL_* or ALERT_EMAIL_*) を確認してください。")

    # normalize recipients into list
    recipients_list = [r.strip() for r in recipients.split(",") if r.strip()]

    msg = EmailMessage()
    # Make headers explicit to help receiving MTAs make correct decisions
    msg["From"] = f"CFD3 Alerts <{smtp_user}>"
    msg["To"] = ", ".join(recipients_list)
    msg["Subject"] = subject
    msg["Reply-To"] = smtp_user
    msg["Sender"] = smtp_user
    # Ensure a Message-ID is present
    try:
        msg["Message-ID"] = make_msgid()
    except Exception:
        # non-fatal
        pass
    msg.set_content(body)

    logger.info("Connecting to %s:%s to send email to %s (recipients=%s)", smtp_host, smtp_port, recipients, recipients_list)
    # Capture smtplib debug output (which prints to stdout when debuglevel>0)
    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
        # enable lib debug prints
        smtp.set_debuglevel(1)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                smtp.login(smtp_user, smtp_pass)
            except Exception:
                logger.exception("SMTP login failed")
                raise
            try:
                # Explicitly pass envelope from and recipient list to avoid ambiguous envelopes
                smtp.send_message(msg, from_addr=smtp_user, to_addrs=recipients_list)
                logger.info("smtp.send_message succeeded")
            except Exception:
                logger.exception("smtp.send_message failed")
                raise
        # log the captured SMTP debug output for further diagnosis
        debug_out = buf.getvalue()
        if debug_out:
            # write to logger (and it will go to whatever handler is configured, e.g., /tmp/webhook_mail.log)
            logger.info("SMTP debug output:\n%s", debug_out)
    # persist smtp outcome to file for audit
    try:
        os.makedirs(os.path.dirname(SMTP_LOG), exist_ok=True)
        with open(SMTP_LOG, 'a', encoding='utf-8') as sl:
            sl.write(json.dumps({
                'ts': datetime.utcnow().isoformat(),
                'to': recipients_list,
                'subject': subject,
                'status': 'sent',
            }, ensure_ascii=False) + "\n")
            if debug_out:
                # store last lines (trim to avoid growing too fast)
                tail = debug_out.splitlines()[-20:]
                sl.write("\n".join(tail) + "\n\n")
    except Exception:
        # non-fatal
        pass


@app.post("/webhook")
async def webhook(request: Request, payload: WebhookPayload):
    """Receive webhook, validate optional token, and forward to Gmail.

    - Token can be sent in header `X-Webhook-Token`.
    - Expects JSON body mapping to WebhookPayload.
    """
    header_token = request.headers.get("X-Webhook-Token", "")
    if WEBHOOK_TOKEN:
        if header_token != WEBHOOK_TOKEN:
            logger.warning("Invalid token: header=%s expected set", header_token)
            raise HTTPException(status_code=403, detail="invalid token")

    # Persist raw payload for traceability (append JSON line)
    try:
        os.makedirs(os.path.dirname(RAW_LOG), exist_ok=True)
        with open(RAW_LOG, 'a', encoding='utf-8') as rf:
            rf.write(json.dumps({"received_at": datetime.utcnow().isoformat(), "payload": payload.dict()}, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("failed to write raw webhook log")

    # Subject prefix to make notifications more visible on small devices
    subject = f"[CFD3] Trading Alert: {payload.symbol or 'signal'} - {payload.signal or ''}".strip()
    body_lines = [f"Symbol: {payload.symbol}", f"Signal: {payload.signal}", "", "Text:", f"{payload.text}", "", "Data:", f"{payload.data}"]
    body = "\n".join([line for line in body_lines if line is not None])

    # Evaluate notify
    eval_detail = _evaluate_notification(payload, request)
    # persist evaluation log
    try:
        os.makedirs(os.path.dirname(NOTIFY_EVAL_LOG), exist_ok=True)
        with open(NOTIFY_EVAL_LOG, 'a', encoding='utf-8') as lf:
            lf.write(json.dumps({
                'received_at': datetime.utcnow().isoformat(),
                'symbol': payload.symbol,
                'detail': eval_detail,
                'payload_preview': {
                    'signal': payload.signal,
                    'text': (payload.text or '')[:200],
                }
            }, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception('failed to write notify eval log')

    if not eval_detail.get('matched'):
        logger.info("skipping email: %s (notify_on=%s, keywords=%s, extracted=%s from %s)", eval_detail.get('reason'), eval_detail.get('notify_on'), eval_detail.get('keywords'), eval_detail.get('extracted_signal'), eval_detail.get('extracted_source'))
    else:
        try:
            send_email(subject, body, GMAIL_TO)
        except Exception as e:
            logger.exception("failed to send email")
            # continue even if email fails — return 500 to caller
            raise HTTPException(status_code=500, detail=str(e))

    # ---- CSV append logic (optional) ----
    # payload may include explicit ohlc fields or a data dict. timeframe may be '60' or '240' or '1h'/'4h'.
    try:
        sym = (payload.symbol or "").upper()
        if sym and (payload.data or payload.open is not None):
            # determine timeframe
            tf = (payload.timeframe or "").lower()
            if tf in ("60","60m","1h","1hour","1-hour"):
                frame = "60"
            elif tf in ("240","4h","4hour","4-hour"):
                frame = "240"
            else:
                # default to 60 if not provided
                frame = "60"

            # extract ohlc
            ohlc = {}
            if payload.open is not None:
                ohlc = {"open": payload.open, "high": payload.high, "low": payload.low, "close": payload.close}
            elif payload.data:
                d = payload.data
                # accept common keys
                for k in ("o","open"): 
                    if k in d:
                        ohlc["open"] = d.get(k)
                        break
                for k in ("h","high"): 
                    if k in d:
                        ohlc["high"] = d.get(k)
                        break
                for k in ("l","low"): 
                    if k in d:
                        ohlc["low"] = d.get(k)
                        break
                for k in ("c","close"): 
                    if k in d:
                        ohlc["close"] = d.get(k)
                        break

            # time
            tval = payload.time or (payload.data.get("time") if payload.data else None)
            if tval is None:
                # use now UTC
                t = pd.Timestamp.now(tz="UTC")
            else:
                # force UTC to avoid boundary drift
                try:
                    t = pd.to_datetime(tval, utc=True)
                except Exception:
                    t = pd.to_datetime(tval)
                    if t.tzinfo is None:
                        t = t.tz_localize("UTC")

            # detect if this is a closed bar
            def _is_bar_closed(pl: WebhookPayload) -> bool:
                try:
                    bs = (pl.barstate or "").lower()
                    if bs in ("closed","close","bar_close","bar_closed"):
                        return True
                except Exception:
                    pass
                try:
                    d = pl.data or {}
                    bs2 = str(d.get("barstate") or d.get("bar_state") or "").lower()
                    if bs2 in ("closed","close","bar_close","bar_closed"):
                        return True
                except Exception:
                    pass
                # heuristic: look for keywords in text
                try:
                    txt = (pl.text or "").lower()
                    if any(k in txt for k in ["bar close","bar_closed","closed bar"]):
                        return True
                except Exception:
                    pass
                return False

            # check time aligns to timeframe boundaries (UTC)
            def _aligns_to_frame(ts: pd.Timestamp, f: str) -> bool:
                ts = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
                if f == "60":
                    return ts.minute == 0 and ts.second == 0
                if f == "240":
                    return ts.minute == 0 and ts.second == 0 and ts.hour % 4 == 0
                return True

            # optional schedule window check in local timezone (e.g., Asia/Tokyo)
            def _within_schedule(ts: pd.Timestamp) -> bool:
                if not SCHEDULE_WINDOWS:
                    return True
                try:
                    # normalize to timezone for comparison
                    if ts.tzinfo is None:
                        ts = ts.tz_localize("UTC")
                    local_ts = ts.tz_convert(IFD_SCHEDULE_TZ)
                except Exception:
                    try:
                        local_ts = ts.tz_convert("UTC") if ts.tzinfo else pd.Timestamp(ts, tz="UTC")
                    except Exception:
                        return True  # fail-open

                for h, m in SCHEDULE_WINDOWS:
                    # build candidate times for today, +/-1 day to handle crossings
                    base = local_ts.replace(hour=h, minute=m, second=0, microsecond=0)
                    for delta in (-1, 0, 1):
                        cand = base + pd.Timedelta(days=delta)
                        try:
                            diff_min = abs((local_ts - cand).total_seconds()) / 60.0
                        except Exception:
                            continue
                        if diff_min <= IFD_SCHEDULE_TOLERANCE_MIN:
                            return True
                return False

            def _schedule_allows(ts: pd.Timestamp) -> bool:
                pol = (IFD_SCHEDULE_POLICY or "gate").lower()
                if pol in ("off", "disable", "disabled"):
                    return True
                if pol in ("prefer", "soft"):
                    # Prefer scheduled times but don't block outside
                    return True
                # default: gate (enforce schedule windows if specified)
                return _within_schedule(ts)

            bar_closed = _is_bar_closed(payload)
            if not bar_closed:
                logger.info("skip CSV append: bar not closed (symbol=%s, frame=%s)", sym, frame)
                # do not run IFD on non-closed bars
                return {"status": "ok", "skipped": "bar_not_closed"}

            # Only proceed if we have symbol and close
            if ohlc.get("close") is not None:
                Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
                fn = os.path.join(DATA_DIR, f"WEBHOOK_{sym}_{frame}.csv")

                # build row dataframe
                row = pd.DataFrame([{ "time": pd.to_datetime(t), "open": float(ohlc.get("open", ohlc.get("close"))), "high": float(ohlc.get("high", ohlc.get("close"))), "low": float(ohlc.get("low", ohlc.get("close"))), "close": float(ohlc.get("close")) }])

                if os.path.exists(fn):
                    try:
                        old = pd.read_csv(fn, parse_dates=[0])
                        # normalize column name for time
                        if old.columns[0].lower() != "time":
                            old.columns = ["time"] + list(old.columns[1:])
                        df = pd.concat([old, row], ignore_index=True)
                    except Exception:
                        df = row
                else:
                    df = row

                # drop duplicates on time keeping last, sort
                df["time"] = pd.to_datetime(df["time"])
                df = df.drop_duplicates(subset=["time"], keep="last").sort_values("time").reset_index(drop=True)
                # write back with ISO times
                df.to_csv(fn, index=False)
                logger.info("wrote webhook csv: %s (rows=%d)", fn, len(df))

                # Optionally trigger IFD run
                if RUN_IFD_ON_WEBHOOK:
                    try:
                        # Determine effective run mode (allow header override per request)
                        try:
                            hdr_mode = (request.headers.get("X-IFD-Run-Mode", "") or "").lower()
                        except Exception:
                            hdr_mode = ""
                        run_mode = hdr_mode or IFD_RUN_MODE

                        # Optional force run header
                        force_run = False
                        try:
                            force_run = (request.headers.get("X-IFD-Force-Run", "").lower() in ("1","true","yes"))
                        except Exception:
                            pass

                        # Enforce run gating based on mode
                        def _should_run(f: str, ts: pd.Timestamp, mode: str, force: bool) -> tuple[bool,str]:
                            if force:
                                return True, "forced"
                            # apply schedule policy gating once
                            if not _schedule_allows(ts):
                                return False, "outside_schedule_window"
                            m = (mode or "").lower()
                            if m in ("manual",):
                                return False, "manual_mode"
                            if m in ("always",):
                                return True, "always_mode"
                            if m in ("closed_60m","closed60","60m"):
                                # run on every closed 60m/240m bar
                                return True, "closed_60m_mode"
                            # default strict_4h
                            if f == "60" and not _aligns_to_frame(ts, "240"):
                                return False, "not_4h_boundary"
                            if f == "240" and not _aligns_to_frame(ts, "240"):
                                return False, "invalid_240_ts"
                            return True, "strict_4h_mode"

                        ok, reason = _should_run(frame, t, run_mode, force_run)
                        if not ok:
                            logger.info("skip IFD run: %s (t=%s, frame=%s, mode=%s)", reason, t, frame, run_mode)
                            return {"status": "ok", "skipped": reason}
                        # locate script in repo root
                        repo_root = Path(__file__).resolve().parents[1]
                        script = repo_root.joinpath("cfd3_portfolio_update_v2.py")
                        if script.exists():
                            logger.info("running IFD script %s", script)
                            # timeframe header override
                            try:
                                hdr_tf = (request.headers.get("X-IFD-Frame", "") or "").strip()
                            except Exception:
                                hdr_tf = ""
                            tf_arg = hdr_tf or IFD_TIMEFRAME or "4h"
                            args = [sys.executable, str(script), "--data", str(DATA_DIR), "--tf", str(tf_arg)]
                            proc = subprocess.run(args, cwd=str(repo_root), capture_output=True, text=True, timeout=120)
                            logger.info("IFD stdout: %s", proc.stdout[:2000])
                            logger.info("IFD stderr: %s", proc.stderr[:2000])
                            # Try to parse JSON blob from IFD stdout and persist it to output/
                            try:
                                out = proc.stdout or ''
                                # find a JSON object in output
                                j = None
                                s = out.strip()
                                if s:
                                    # if entire stdout is JSON
                                    try:
                                        j = json.loads(s)
                                    except Exception:
                                        # attempt to extract first {...} block
                                        first = s.find('{')
                                        last = s.rfind('}')
                                        if first != -1 and last != -1 and last > first:
                                            try:
                                                j = json.loads(s[first:last+1])
                                            except Exception:
                                                j = None
                                if j:
                                    run_id = j.get('run_id') or datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                                    out_dir = os.path.join(os.path.dirname(__file__), '..', 'output')
                                    os.makedirs(out_dir, exist_ok=True)
                                    out_fp = os.path.join(out_dir, f'ifd_{run_id}.json')
                                    with open(out_fp, 'w', encoding='utf-8') as wf:
                                        json.dump(j, wf, ensure_ascii=False, indent=2)
                                    logger.info('Saved IFD JSON to %s', out_fp)
                                    # Also append a compact summary CSV for quick audit
                                    try:
                                        log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
                                        os.makedirs(log_dir, exist_ok=True)
                                        summary_fp = os.path.join(log_dir, f'ifd_summary_{datetime.utcnow().strftime("%Y%m%d")}.csv')
                                        # build rows from j['orders'] if present
                                        rows = []
                                        for order in j.get('orders', []):
                                            inst = order.get('instrument') or ''
                                            decision = order.get('decision') or ''
                                            entry = ''
                                            sl = ''
                                            tp1 = ''
                                            tp2 = ''
                                            lots = ''
                                            try:
                                                entry = str(order.get('entry_order', {}).get('price', ''))
                                            except Exception:
                                                entry = ''
                                            # attempt to extract from ifd_legs OCOs
                                            legs = order.get('ifd_legs') or []
                                            if legs and isinstance(legs, list):
                                                try:
                                                    # take first OCO TP/SL
                                                    oco = legs[0].get('oco', {})
                                                    tp = oco.get('take_profit') or {}
                                                    slv = oco.get('stop_loss') or {}
                                                    tp1 = str(tp.get('price','')) if isinstance(tp, dict) else ''
                                                    sl = str(slv.get('price','')) if isinstance(slv, dict) else ''
                                                except Exception:
                                                    pass
                                            lots = str(order.get('lots',''))
                                            rows.append((run_id, datetime.utcnow().isoformat(), inst, decision, entry, sl, tp1, tp2, lots))
                                        # append header if file not exists
                                        write_header = not os.path.exists(summary_fp)
                                        import csv
                                        with open(summary_fp, 'a', newline='', encoding='utf-8') as cf:
                                            writer = csv.writer(cf)
                                            if write_header:
                                                writer.writerow(['run_id','ts','instrument','decision','entry','SL','TP1','TP2','lots'])
                                            for r in rows:
                                                writer.writerow(r)
                                        logger.info('Appended IFD summary to %s', summary_fp)
                                    except Exception:
                                        logger.exception('Failed to append IFD summary')
                            except Exception:
                                logger.exception('Failed to persist IFD JSON')
                        else:
                            logger.warning("IFD script not found at %s", script)
                    except Exception:
                        logger.exception("IFD run failed")

    except Exception:
        logger.exception("failed to append CSV from webhook payload")

    return {"status": "ok"}


@app.post("/webhook/test")
async def webhook_test(request: Request, payload: WebhookPayload):
    """Simple echo endpoint for testing connectivity from TradingView or curl.

    Sends the same email forward and returns the parsed payload and where a CSV would be written.
    """
    header_token = request.headers.get("X-Webhook-Token", "")
    if WEBHOOK_TOKEN and header_token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=403, detail="invalid token")

    # echo back
    return {"received": payload.dict(), "data_dir": DATA_DIR, "run_ifd": RUN_IFD_ON_WEBHOOK}


# Export the ASGI app as `app` so uvicorn or TestClient can import it.


@app.post("/ifd/run")
async def ifd_run(req: IfdRunRequest):
    """Manual trigger to run the IFD generator now.

    Request fields:
    - symbols: comma-separated instruments passed to --only
    - single: include --single when True
    - expiry_hours: integer hours passed to --expiry-hours
    - trade_mode: passed to --trade-mode
    - data_dir: override for --data (defaults to DATA_DIR)
    """
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root.joinpath("cfd3_portfolio_update_v2.py")
    if not script.exists():
        raise HTTPException(status_code=404, detail=f"IFD script not found: {script}")

    args = [sys.executable, str(script), "--data", str(req.data_dir or DATA_DIR)]
    if req.tf:
        args += ["--tf", str(req.tf)]
    if req.single:
        args.append("--single")
    if req.expiry_hours is not None:
        args += ["--expiry-hours", str(int(req.expiry_hours))]
    if req.trade_mode:
        args += ["--trade-mode", str(req.trade_mode)]
    only = req.only or req.symbols
    if only:
        args += ["--only", only]

    try:
        proc = subprocess.run(args, cwd=str(repo_root), capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="IFD run timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"IFD run failed: {e}")

    # Try to parse JSON from stdout
    out = proc.stdout or ''
    j = None
    s = out.strip()
    if s:
        try:
            j = json.loads(s)
        except Exception:
            first = s.find('{')
            last = s.rfind('}')
            if first != -1 and last != -1 and last > first:
                try:
                    j = json.loads(s[first:last+1])
                except Exception:
                    j = None

    resp = {
        "args": args,
        "returncode": proc.returncode,
        "stdout": out[:4000],
        "stderr": (proc.stderr or '')[:4000],
        "parsed": bool(j is not None),
    }
    if j:
        resp["ifd_json"] = j
    return resp


# 画像を安全に読み取る関数（Cloudflare / Streamlit / UploadFile 対応版）
async def read_uploaded_image(file: UploadFile) -> bytes:
    """
    アップロードされた画像を安全に読み取る
    
    Args:
        file: FastAPI UploadFile オブジェクト
    
    Returns:
        画像のバイトデータ
    
    Raises:
        HTTPException: 画像の読み取りに失敗した場合
    """
    try:
        contents = await file.read()

        # FastAPI / UploadFile の仕様で read() が空になることがあるため
        if not contents or len(contents) < 10:
            raise ValueError("アップロード画像が空です。")

        return contents

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"画像の読み取りに失敗: {e}")


# --- 画像前処理（輝度 + コントラスト + シャープ化 + 中央トリミング） ---
def preprocess_image_for_vision(img_bytes: bytes) -> bytes:
    """
    画像を前処理してVision APIに渡す
    - 明るさアップ
    - コントラストアップ
    - シャープ化
    - 中央部分トリミング
    """
    try:
        # OpenCV高度前処理（失敗時は元バイト列）
        try:
            from webhook_mail.opencv_preprocess import preprocess_image as cv_pre
            img_bytes = cv_pre(img_bytes)
        except Exception:
            pass
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        # 明るさアップ
        img = ImageEnhance.Brightness(img).enhance(1.3)
        # コントラストアップ
        img = ImageEnhance.Contrast(img).enhance(1.4)
        # シャープ化
        img = img.filter(ImageFilter.SHARPEN)

        # 中央部分トリミング
        w, h = img.size
        top = int(h * 0.15)
        bottom = int(h * 0.65)
        left = int(w * 0.05)
        right = int(w * 0.95)
        img = img.crop((left, top, right, bottom))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return img_bytes


# --- OCRバックアップ（Visionが失敗したとき） ---
def fallback_ocr_entry(img_bytes: bytes) -> float | None:
    """
    Tesseract OCRで価格を抽出（Vision失敗時のバックアップ）
    """
    if pytesseract is None:
        return None
    try:
        img = Image.open(io.BytesIO(img_bytes))
        text = pytesseract.image_to_string(img, lang="eng+jpn")
        nums = [float(x.replace(",", "")) for x in re.findall(r"\d+\.\d+|\d+", text)]
        if not nums:
            return None
        return max(nums)  # 一番大きな数字を現在値とみなす
    except Exception:
        return None


# --- OCRバックアップ（銘柄名の推定） ---
def fallback_ocr_symbol(img_bytes: bytes) -> str | None:
    """
    スマホスクショなどでVisionが銘柄名を検出できなかった場合に、
    画面上部の文字列から銘柄名をOCRで推定する。
    """
    if pytesseract is None:
        return None
    try:
        img = Image.open(io.BytesIO(img_bytes))
        w, h = img.size

        # 銘柄名は上部10〜25%くらいに表示される
        top = 0
        bottom = int(h * 0.25)
        cropped = img.crop((0, top, w, bottom))

        text = pytesseract.image_to_string(cropped, lang="eng+jpn")
        text = text.strip().upper()

        # よく使うCFD銘柄キーワードから検出
        candidates = ["JP225", "NAS100", "GER40", "US30", "XAUUSD", "BTCUSD", "SP500"]
        for c in candidates:
            if c in text:
                return c

        # フリーテキストに "225" や "GER" があればそれを返す
        if "225" in text:
            return "JP225"
        if "GER" in text:
            return "GER40"
        if "NAS" in text:
            return "NAS100"
        if "GOLD" in text or "XAU" in text:
            return "XAUUSD"

        return None
    except Exception:
        return None


# --- JSON抽出 ---
def _safe_parse_json_from_text(text: str) -> dict:
    """
    テキストからJSONを抽出（マークダウンコードブロック対応）
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        body = []
        for line in lines[1:]:
            if line.strip().startswith("```"):
                break
            body.append(line)
        text = "\n".join(body).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        return json.loads(text)
    except Exception:
        return {}


# --- Vision解析 ---
def analyze_image_with_ai(image_bytes: bytes, symbol_hint: str | None = None) -> dict:
    """
    OpenAI Vision APIで画像を解析
    - 前処理を適用
    - Visionで解析
    - 失敗時はOCRバックアップ
    """
    processed_bytes = preprocess_image_for_vision(image_bytes)

    base_prompt = f"""
あなたはCFDトレードに詳しいアナリストです。
次の画像（GMOクリック証券などのCFDウォッチリストやチャート）を解析し、
以下のJSONだけを返してください。

{{
  "symbol": "GER40",
  "direction": "buy",
  "entry": 23136.9,
  "change_percent": 0.7,
  "signal": "GO",
  "confidence": 80,
  "comment": "上昇傾向で買い優勢"
}}
"""

    def call_vision(prompt: str) -> dict:
        # Chat Completions API は image_url 形式を期待するため data URL に変換
        b64 = base64.b64encode(processed_bytes).decode("utf-8")
        data_url = f"data:image/png;base64,{b64}"
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            temperature=0.0,
        )
        msg = res.choices[0].message
        content = getattr(msg, "content", "") or ""
        return _safe_parse_json_from_text(content)

    data = call_vision(base_prompt)

    # --- Visionが失敗したらOCRで救済 ---
    entry = data.get("entry")
    if not entry:
        entry = fallback_ocr_entry(processed_bytes)
        if entry:
            data["entry"] = entry

    # --- 数値フィルタ：10万以上の価格は誤検出扱いで再試行 ---
    try:
        if float(data.get("entry", 0)) > 100000 or float(data.get("entry", 0)) < 100:
            logger.warning("⚠️ entry 値 %.1f が異常 → Vision再試行（グレースケール再処理）", float(data.get("entry", 0)))

            # グレースケール再処理でコントラスト強化
            img = Image.open(io.BytesIO(image_bytes)).convert("L")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            gray_bytes = buf.getvalue()
            retry_prompt = base_prompt + "\n\nもう一度、画面中央の価格に注目して正確な現在値（エントリー）を1つだけ抽出してください。"
            # gray_bytes も data URL に変換して送信
            b64g = base64.b64encode(gray_bytes).decode("utf-8")
            gray_url = f"data:image/png;base64,{b64g}"
            res_retry = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": retry_prompt},
                            {"type": "image_url", "image_url": {"url": gray_url}},
                        ],
                    }
                ],
                temperature=0.0,
            )
            msg_retry = res_retry.choices[0].message
            content_retry = getattr(msg_retry, "content", "") or ""
            data_retry = _safe_parse_json_from_text(content_retry)

            if data_retry.get("entry") and 100 < float(data_retry["entry"]) < 100000:
                logger.info("🔁 Vision再試行成功 → entry %.2f に修正", float(data_retry["entry"]))
                data = data_retry
            else:
                logger.error("❌ Vision再試行失敗：妥当な entry を取得できませんでした。")
    except Exception as e:
        logger.exception(f"Vision再試行処理中に例外発生: {e}")

    # --- 銘柄補完（Vision→OCRの順） ---
    symbol = (data.get("symbol") or symbol_hint or "UNKNOWN").upper()
    if symbol == "UNKNOWN":
        ocr_symbol = fallback_ocr_symbol(image_bytes)
        if ocr_symbol:
            symbol = ocr_symbol

    direction = (data.get("direction") or "buy").lower()
    signal = (data.get("signal") or "GO").upper()
    confidence = int(data.get("confidence") or 0)
    comment = data.get("comment") or "Vision解析またはOCRからの推定"

    return {
        "symbol": symbol,
        "direction": direction,
        "entry": data.get("entry"),
        "signal": signal,
        "confidence": confidence,
        "comment": comment,
        "raw": data,
    }


@app.post("/analyze/image")
async def analyze_image(symbol: Optional[str] = None, file: UploadFile = File(...)):
    """
    GMO等のスクショ画像を受け取り、AIで方向・価格帯を解析し、
    manual30_ifd.generate_ifd(...) で IFD を生成して返す。
    """
    print("★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★")
    print("★★ /analyze/image にリクエストが来ました ★★")
    print("★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★")
    
    logger.info("=" * 80)
    logger.info("🔥 /analyze/image エンドポイントが呼ばれました！")
    logger.info("Symbol: %s", symbol)
    logger.info("File: %s", file.filename if file else "None")
    logger.info("=" * 80)
    
    try:
        # 1) 画像読み取り
        img_bytes = await read_uploaded_image(file)
        logger.info("✅ 画像読み込み完了: %d bytes", len(img_bytes))

        # 2) Vision解析（前処理 + OCRバックアップ付き）
        logger.info("🤖 OpenAI Vision API 呼び出し中（前処理 + OCRバックアップ付き）...")
        analysis = analyze_image_with_ai(img_bytes, symbol_hint=symbol)
        logger.info("✅ Vision解析結果: %s", analysis)

        # 解析結果から値を取得
        result_symbol = analysis.get("symbol") or symbol or "JP225"
        direction = analysis.get("direction")
        entry = analysis.get("entry")
        confidence = analysis.get("confidence") or 50

        if not entry or entry == 0:
            return {
                "status": "success",
                "symbol": result_symbol,
                "analysis": analysis,
                "ifd": {"error": "エントリー価格が取得できませんでした（Vision + OCR両方失敗）"},
            }

        # 3) manual30_ifd.generate_ifd を呼び出し
        try:
            # シグナル判定
            signal = analysis.get("signal") or ("STRONG_GO" if confidence >= 80 else "GO")
            
            logger.info("📦 IFD生成パラメータ: symbol=%s, direction=%s, entry=%s, signal=%s",
                       result_symbol, direction, entry, signal)
            
            # manual30_ifd モジュールをインポート
            repo_root = Path(__file__).resolve().parents[1]
            sys.path.insert(0, str(repo_root))
            import manual30_ifd
            
            ifd = manual30_ifd.generate_ifd(
                symbol=result_symbol,
                direction=direction,
                entry=float(entry),
                signal=signal,
            )
            
            logger.info("✅ IFD生成成功")
            
            # --- Markdownテーブル生成 ---
            # IFD内部から値を取得
            order = ifd.get("orders", [{}])[0]
            trade_mode = ifd.get("trade_mode", "MANUAL_30M")
            lots = order.get("lots", 1)
            entry_price = order.get("entry_order", {}).get("price", entry)
            
            oco = order.get("ifd_legs", [{}])[0].get("oco", {})
            tp_price = oco.get("take_profit", {}).get("price", 0)
            sl_price = oco.get("stop_loss", {}).get("price", 0)
            
            # 日本語化
            direction_jp = "買い" if direction.lower() == "buy" else "売り"
            
            # Markdownテーブル生成
            ifd_markdown = f"""
| trade_mode | 銘柄 | 方向 | entry_price | SL | TP1 | TP2 | order_type | 判定 | ニュースロック | 推奨度 | ロット | CUT条件 |
|-------------|------|------|--------------|------|------|------|-------------|--------|----------------|----------|--------|-----------|
| {trade_mode} | {result_symbol} | {direction_jp} | {entry_price:.1f} | {sl_price:.1f} | {tp_price:.1f} | - | 指値 | {signal} | false | ★★★★★ | {lots} | SMA25＜SMA75 または MACD＜Signal |
"""
            
            # --- Google Sheets 記録（オプション） ---
            try:
                record = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "symbol": result_symbol,
                    "direction": direction,
                    "entry": float(entry_price) if entry_price is not None else "",
                    "tp": float(tp_price) if tp_price else "",
                    "sl": float(sl_price) if sl_price else "",
                    "signal": signal,
                    "confidence": int(confidence) if confidence is not None else "",
                    "comment": analysis.get("comment") or ""
                }
                write_to_sheets(record)
            except Exception:
                logger.exception("Sheets logging failed")
            
            return {
                "status": "success",
                "symbol": result_symbol,
                "analysis": analysis,
                "ifd": ifd,
                "ifd_markdown": ifd_markdown,
            }
        except Exception as e:
            logger.exception("IFD生成でエラー: %s", e)
            return {
                "status": "success",
                "symbol": result_symbol,
                "analysis": analysis,
                "ifd": {"error": str(e)},
            }
    
    except Exception as e:
        logger.exception("❌ /analyze/image でエラー発生")
        raise HTTPException(status_code=500, detail=str(e))

