#!/usr/bin/env python3
"""
alerts.py

Small helper to send alert emails via yagmail. Uses environment variables:
  - EMAIL_USER (optional)
  - EMAIL_PASS (optional)
  - RECIPIENT (optional override)

Usage:
  from alerts import send_alert
  send_alert('you@example.com', 'subject', 'body text', attachments=[])
"""
import os
import sys
import time

def _get_creds():
    user = os.environ.get('EMAIL_USER') or os.environ.get('GMAIL_USER')
    pwd = os.environ.get('EMAIL_PASS') or os.environ.get('GMAIL_PASS')
    return user, pwd

def send_alert(recipient: str, subject: str, body: str, attachments: list = None) -> bool:
    attachments = attachments or []
    user, pwd = _get_creds()
    try:
        import yagmail
    except Exception as e:
        print('yagmail not installed; cannot send alert:', e)
        return False

    try:
        if user and pwd:
            yag = yagmail.SMTP(user, pwd)
        elif user and not pwd:
            yag = yagmail.SMTP(user)
        else:
            yag = yagmail.SMTP()
        yag.send(to=recipient, subject=subject, contents=body, attachments=attachments)
        print(f'Alert email sent to {recipient}')
        return True
    except Exception as e:
        print('Failed to send alert email:', e)
        return False

if __name__ == '__main__':
    # simple CLI for testing
    if len(sys.argv) < 3:
        print('Usage: alerts.py recipient subject [body]')
        sys.exit(2)
    recipient = sys.argv[1]
    subject = sys.argv[2]
    body = sys.argv[3] if len(sys.argv) > 3 else ''
    send_alert(recipient, subject, body)
