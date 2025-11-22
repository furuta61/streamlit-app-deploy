#!/usr/bin/env python3
"""
post_run_automation_fixed.py
A clean replacement for post_run_automation.py (safe, keyring-based email creds).
"""

import os
import subprocess
import pandas as pd
from datetime import datetime
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
import keyring

OUTPUT_DIR = Path.home() / "Desktop/CFD3_AutoSystem/output_production"
DRIVE_DIR = Path.home() / "Google ドライブ/CFD3Pro"


def load_email_credentials():
    from_addr = os.environ.get('CFD3_FROM')
    to_addr = os.environ.get('CFD3_TO')
    pwd = None
    if from_addr:
        try:
            pwd = keyring.get_password('CFD3_MAIL', from_addr)
        except Exception:
            pwd = None
    return from_addr, to_addr, pwd


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


def send_email(subject: str, body: str, from_addr: str, to_addr: str, password: str):
    print('--- send_email would run with:', from_addr, to_addr)
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = from_addr
        msg['To'] = to_addr
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(from_addr, password)
            server.send_message(msg)
        print('📨 メール送信成功')
    except Exception as e:
        print('⚠️ メール送信エラー:', e)


def main():
    latest = find_latest_csv(OUTPUT_DIR)
    if latest is None:
        return
    df = summary_csv(latest)
    drive_path = sync_to_drive(latest, DRIVE_DIR)
    from_addr, to_addr, pwd = load_email_credentials()
    if from_addr and to_addr and pwd:
        signals = extract_strong_signals(df)
        if signals is not None:
            body = '【CFD3 AutoSystem】Strong Signals Detected:\n\n' + signals.to_string(index=False)
            print('Would send email with body:\n', body)
            # Uncomment next line to actually send
            # send_email('CFD3 AutoSystem: STRONG TRADE ALERT', body, from_addr, to_addr, pwd)
        else:
            print('No strong signals')
    else:
        print('Email not configured; skipping send')

if __name__ == '__main__':
    main()
