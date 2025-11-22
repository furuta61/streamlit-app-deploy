#!/usr/bin/env python3
"""
post_run_automation_fixed.py
A clean replacement for post_run_automation.py (safe, keyring-based email creds).
"""

# ==== 設定（先頭付近）====
ENABLE_EMAIL = True  # True にしてメール送信を有効化

# SMTP は環境変数で上書き可能（デフォルトは iCloud）。
# 例: export SMTP_SERVER=smtp.gmail.com; export SMTP_PORT=587
import os
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.mail.me.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# 環境変数を優先（CFD3_FROM/CFD3_TO）、無ければ既定値を使う
FROM_ADDR = os.getenv("CFD3_FROM", "furuta61@icloud.com")
TO_ADDR   = os.getenv("CFD3_TO",   "furuta61@gmail.com")
import subprocess
import pandas as pd
from datetime import datetime
from pathlib import Path
import argparse
import smtplib
from email.mime.text import MIMEText
import keyring
import shlex
import urllib.request
import urllib.parse
import json
import ssl
import certifi
import urllib.error

OUTPUT_DIR = Path.home() / "Desktop/CFD3_AutoSystem/output_production"
DRIVE_DIR = Path.home() / "Google ドライブ/CFD3Pro"


def load_email_credentials():
    """Return (from_addr, to_addr, password).
    Password is fetched from keyring service 'CFD3_MAIL' with account=from_addr.
    """
    from_addr = os.environ.get('CFD3_FROM', FROM_ADDR)
    # allow multiple recipients separated by comma
    to_env = os.environ.get('CFD3_TO', None)
    to_addr = to_env if to_env is not None else TO_ADDR
    # normalize to list
    recipients = [a.strip() for a in to_addr.split(',') if a.strip()]
    pwd = None
    try:
        pwd = keyring.get_password('CFD3_MAIL', from_addr)
    except Exception:
        pwd = None
    return from_addr, recipients, pwd


def find_latest_csv(output_dir: Path):
    if not output_dir.exists():
        print(f"❌ Output dir does not exist: {output_dir}")
        return None
    csvs = list(output_dir.glob("events_scored_*.csv"))
    if not csvs:
        print(f"❌ No events_scored_*.csv found in {output_dir}")
        return None
    latest = max(csvs, key=lambda p: p.stat().st_mtime)
    print(f"🕒 最新ファイルを検出: {latest}")
    return latest


def summary_csv(path: Path):
    df = pd.read_csv(path)
    print(df.head())
    return df


def sync_to_drive(src: Path, drive_dir: Path):
    drive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    dest = drive_dir / f"events_scored_{timestamp}.csv"
    subprocess.run(["cp", str(src), str(dest)], check=True)
    print(f"✅ Driveフォルダに保存完了: {dest}")
    return dest


def extract_strong_signals(df: pd.DataFrame):
    if 'signal' not in df.columns or 'confidence' not in df.columns:
        return None
    strong = df[(df['signal'].isin(['BUY', 'SELL'])) & (df['confidence'] > 0.8)]
    if strong.empty:
        print("📭 Strongシグナルは検出されませんでした。メール送信をスキップ。")
        return None
    print(f"📨 {len(strong)}件のStrongシグナルを検出、メール送信します。")
    cols = [c for c in ['datetime', 'signal', 'confidence', 'entry', 'TP', 'SL'] if c in strong.columns]
    return strong[cols]


def send_email(subject: str, body: str):
    """Send email using configured SMTP server and keyring-stored password.
    Supports Gmail (smtp.gmail.com:587) as well as iCloud defaults. Password must
    be stored with keyring service 'CFD3_MAIL' and account equal to FROM_ADDR.
    """
    from_addr, recipients, pwd = load_email_credentials()
    to_addr = ', '.join(recipients)

    # If no password is available, fall back to Mail.app (osascript) if possible.
    if not pwd:
        print(f"⚠️ Keychain からパスワードを取得できませんでした: service='CFD3_MAIL' account='{from_addr}'")
        if os.getenv('CFD3_FORCE_MAILAPP', '1') == '1':
            print('ℹ️ Mail.app フォールバックを試みます...')
            ok = send_via_mailapp(subject, body, from_addr, recipients)
            if ok:
                print('✅ Mail.app 経由で送信しました')
            else:
                print('❌ Mail.app 経由でも送信できませんでした')
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    domain = from_addr.split("@")[-1].lower() if "@" in from_addr else ""
    # Gmail の場合は STARTTLS で smtp.gmail.com:587 を使う（デフォルトで SMTP_SERVER を上書き可能）
    server = os.getenv('SMTP_SERVER', SMTP_SERVER)
    port = int(os.getenv('SMTP_PORT', SMTP_PORT))

    # Try STARTTLS first (most providers including Gmail and iCloud)
    try:
        with smtplib.SMTP(server, port, timeout=20) as s:
            s.ehlo()
            # If server supports starttls and port is 587, try it
            try:
                s.starttls()
                s.ehlo()
            except Exception:
                pass
            try:
                s.login(from_addr, pwd)
                s.send_message(msg)
                print(f"✅ メール送信完了 (STARTTLS) → {to_addr} via {server}:{port}")
                # local macOS notification (helps when mail notifications are off)
                try:
                    send_local_notification('CFD3 AutoSystem', f'Mail sent (SMTP) to: {to_addr}')
                    send_pushover('CFD3 AutoSystem', f'Mail sent (SMTP) to: {to_addr}')
                except Exception:
                    pass
                return
            except smtplib.SMTPAuthenticationError as e:
                print(f"ℹ️ 認証失敗 (STARTTLS): {e}")
    except Exception as e:
        print(f"ℹ️ STARTTLS 接続失敗: {e}")

    # If SMTP_SSL (465) is desired, try it
    try:
        with smtplib.SMTP_SSL(server, 465, timeout=20) as s:
            s.ehlo()
            try:
                s.login(from_addr, pwd)
                s.send_message(msg)
                print(f"✅ メール送信完了 (SSL) → {to_addr} via {server}:465")
                try:
                    send_local_notification('CFD3 AutoSystem', f'Mail sent (SSL) to: {to_addr}')
                    send_pushover('CFD3 AutoSystem', f'Mail sent (SSL) to: {to_addr}')
                except Exception:
                    pass
                return
            except smtplib.SMTPAuthenticationError as e:
                print(f"ℹ️ 認証失敗 (SSL): {e}")
    except Exception as e:
        print(f"ℹ️ SSL 接続失敗: {e}")

    print("❌ メール送信に失敗しました。設定と Keychain のアプリパスワードを確認してください。")
    # If SMTP failed, optionally try Mail.app as a fallback (default: enabled)
    if os.getenv('CFD3_FALLBACK_MAILAPP', '1') == '1':
        print('ℹ️ SMTP が失敗したため Mail.app フォールバックを試みます...')
        ok = send_via_mailapp(subject, body, from_addr, recipients)
        if ok:
            print('✅ Mail.app 経由で送信しました（フォールバック）')
            try:
                send_local_notification('CFD3 AutoSystem', f'Mail sent (Mail.app) to: {to_addr}')
                send_pushover('CFD3 AutoSystem', f'Mail sent (Mail.app) to: {to_addr}')
            except Exception:
                pass
            return
        else:
            print('❌ Mail.app フォールバックでも送信できませんでした')


def send_via_mailapp(subject: str, body: str, from_addr: str, recipients) -> bool:
    """Use macOS Mail.app via AppleScript (osascript) to send a simple plain-text message.
    recipients may be a single string or a list of addresses. Returns True on success.
    """
    # Prepare AppleScript-safe strings
    def esc(s: str) -> str:
        return s.replace('\\', '\\\\').replace('"', '\\"')

    a_subject = esc(subject)
    a_body = esc(body)

    # normalize recipients to list
    if isinstance(recipients, str):
        recipients_list = [r.strip() for r in recipients.split(',') if r.strip()]
    else:
        recipients_list = [r.strip() for r in recipients]

    # build recipient lines for AppleScript (multiple make new to recipient ...)
    recipient_lines = ''
    for addr in recipients_list:
        a_addr = esc(addr)
        recipient_lines += f'    make new to recipient at end of to recipients with properties {{address:"{a_addr}"}}\n'

    applescript = (
        'tell application "Mail"\n'
        f'  set newMessage to make new outgoing message with properties {{subject:"{a_subject}", content:"{a_body}", visible:false}}\n'
        '  tell newMessage\n'
        f'{recipient_lines}'
        '    send\n'
        '  end tell\n'
        'end tell'
    )
    try:
        subprocess.run(['osascript', '-e', applescript], check=True, timeout=20)
        return True
    except Exception as e:
        print('ℹ️ Mail.app 送信で例外が発生しました:', e)
        return False


def send_local_notification(title: str, message: str) -> bool:
    """Display a macOS notification via AppleScript (osascript).
    Returns True if the osascript call succeeded. Note: this requires the
    user to allow notifications for the running app (Terminal/Python).
    """
    def esc(s: str) -> str:
        return s.replace('\\', '\\\\').replace('"', '\\"')

    a_title = esc(title)
    a_msg = esc(message)
    script = f'display notification "{a_msg}" with title "{a_title}"'
    try:
        subprocess.run(['osascript', '-e', script], check=True, timeout=5)
        return True
    except Exception as e:
        print('ℹ️ ローカル通知に失敗しました:', e)
        return False


def get_pushover_credentials():
    """Return (user_key, app_token) from keyring or environment variables.
    Keyring service: 'CFD3_PUSHOVER', accounts: 'user' and 'app'
    Environment vars fallback: PUSHOVER_USER, PUSHOVER_TOKEN
    """
    user = None
    app = None
    try:
        user = keyring.get_password('CFD3_PUSHOVER', 'user')
        app = keyring.get_password('CFD3_PUSHOVER', 'app')
    except Exception:
        user = None
        app = None
    if not user:
        user = os.environ.get('PUSHOVER_USER')
    if not app:
        app = os.environ.get('PUSHOVER_TOKEN')
    return user, app


def get_telegram_credentials():
    """Return (token, chat_id) from keyring or environment variables.
    Keyring service: 'CFD3_TELEGRAM', accounts: 'token' and 'chat'
    Env fallback: TELEGRAM_TOKEN, TELEGRAM_CHAT
    """
    token = None
    chat = None
    try:
        token = keyring.get_password('CFD3_TELEGRAM', 'token')
        chat = keyring.get_password('CFD3_TELEGRAM', 'chat')
    except Exception:
        token = None
        chat = None
    if not token:
        token = os.environ.get('TELEGRAM_TOKEN')
    if not chat:
        chat = os.environ.get('TELEGRAM_CHAT')
    return token, chat


def send_telegram(text: str) -> bool:
    """Send a Telegram message using Bot API. Returns True on success."""
    token, chat = get_telegram_credentials()
    if not token or not chat:
        print('ℹ️ Telegram credentials not found (skipping)')
        return False
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = urllib.parse.urlencode({'chat_id': chat, 'text': text}).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    try:
        # Use certifi context to avoid cert issues
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            resp_data = resp.read().decode('utf-8')
            j = json.loads(resp_data)
            if j.get('ok'):
                return True
            else:
                print('ℹ️ Telegram response:', j)
                return False
    except urllib.error.HTTPError as he:
        try:
            body = he.read().decode('utf-8')
            print('ℹ️ Telegram HTTPError:', he.code, he.reason, 'body=', body)
            try:
                j = json.loads(body)
                print('ℹ️ Telegram error JSON:', j)
            except Exception:
                pass
        except Exception as e2:
            print('ℹ️ Failed to read Telegram HTTPError body:', e2)
        return False
    except Exception as e:
        print('ℹ️ Telegram send failed:', e)
        return False


def send_pushover(title: str, message: str, priority: int = 0) -> bool:
    """Send a push via Pushover API. Returns True on success.
    Requires PUSHOVER_USER and PUSHOVER_TOKEN in env or keyring entries.
    """
    user, token = get_pushover_credentials()
    if not user or not token:
        print('ℹ️ Pushover credentials not found (skipping)')
        return False
    data = {
        'token': token,
        'user': user,
        'message': message,
        'title': title,
        'priority': str(priority),
    }
    try:
        encoded = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request('https://api.pushover.net/1/messages.json', data=encoded)
        # Use certifi CA bundle to avoid macOS/python cert issues
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            resp_data = resp.read().decode('utf-8')
            j = json.loads(resp_data)
            if j.get('status') == 1:
                return True
            else:
                print('ℹ️ Pushover response:', j)
                return False
    except urllib.error.HTTPError as he:
        try:
            body = he.read().decode('utf-8')
            print('ℹ️ Pushover HTTPError:', he.code, he.reason, 'body=', body)
            try:
                j = json.loads(body)
                print('ℹ️ Pushover error JSON:', j)
            except Exception:
                pass
        except Exception as e2:
            print('ℹ️ Failed to read HTTPError body:', e2)
        return False
    except Exception as e:
        print('ℹ️ Pushover send failed:', e)
        return False


def main(latest_override: Path | None = None):
    """Run the post-run automation.

    latest_override: if provided, use this Path as the CSV to process instead of
    finding the newest file in OUTPUT_DIR.
    """
    if latest_override:
        latest = Path(latest_override)
        if not latest.exists():
            print(f"❌ 指定ファイルが存在しません: {latest}")
            return
    else:
        latest = find_latest_csv(OUTPUT_DIR)
        if latest is None:
            return

    df = summary_csv(latest)
    # always archive the full scored CSV to Drive-sync folder for auditing
    drive_path = sync_to_drive(latest, DRIVE_DIR)

    # If the pipeline produced an 'action' column (Balanced rules), honor it.
    if 'action' in df.columns:
        # TRADE rows -> produce a production CSV in Drive and notify
        trades = df.loc[df['action'] == 'TRADE']
        watches = df.loc[df['action'] == 'WATCH']

        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        if not trades.empty:
            DRIVE_DIR.mkdir(parents=True, exist_ok=True)
            prod_path = DRIVE_DIR / f"events_scored_{timestamp}_TRADE.csv"
            trades.to_csv(prod_path, index=False)
            print(f"✅ TRADE 行を本番Driveに保存しました: {prod_path} (件数={len(trades)})")
            # notify
            body = '【CFD3 AutoSystem】TRADE proposals:\n\n' + trades.to_string(index=False)
            if ENABLE_EMAIL:
                send_email('CFD3 AutoSystem: TRADE Proposals', body)
            else:
                print('EMAIL DISABLED - TRADE body:\n', body)
            # push notifications
            try:
                send_pushover('CFD3 AutoSystem TRADE', f'{len(trades)} TRADE proposals saved to Drive')
                send_telegram(f'CFD3 AutoSystem: {len(trades)} TRADE proposals saved to Drive')
            except Exception:
                pass
        else:
            print('ℹ️ TRADE 行はありませんでした。')

        # WATCH rows -> notify only (do not copy to production)
        if not watches.empty:
            print(f'ℹ️ WATCH 行を検出しました（件数={len(watches)}）: 通知のみ実施します')
            body = '【CFD3 AutoSystem】WATCH list:\n\n' + watches.to_string(index=False)
            if ENABLE_EMAIL:
                send_email('CFD3 AutoSystem: WATCH list', body)
            else:
                print('EMAIL DISABLED - WATCH body:\n', body)
            try:
                send_pushover('CFD3 AutoSystem WATCH', f'{len(watches)} WATCH items')
                send_telegram(f'CFD3 AutoSystem: {len(watches)} WATCH items')
            except Exception:
                pass
        else:
            print('ℹ️ WATCH 行はありませんでした。')

        # If neither TRADE nor WATCH produced rows, inform and exit
        if trades.empty and watches.empty:
            print('ℹ️ action 列の結果: TRADE/WATCH はありませんでした。')
        return

    # Fallback for older outputs without 'action' column: keep original strong-signal behavior
    signals = extract_strong_signals(df)
    if signals is not None:
        body = '【CFD3 AutoSystem】Strong Signals Detected:\n\n' + signals.to_string(index=False)
        if ENABLE_EMAIL:
            send_email('CFD3 AutoSystem: STRONG TRADE ALERT', body)
        else:
            print('EMAIL DISABLED (ENABLE_EMAIL=False) - would send body:\n', body)
    else:
        print('No strong signals')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Post-run automation: sync latest events_scored CSV and alert on strong signals')
    parser.add_argument('--file', '-f', dest='file', help='Path to a specific events_scored CSV to process')
    args = parser.parse_args()
    if args.file:
        main(Path(args.file))
    else:
        main()
