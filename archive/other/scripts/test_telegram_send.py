#!/usr/bin/env python3
"""
Local test runner for sending a Telegram message using token/chat stored in keyring.

Usage:
  python scripts/test_telegram_send.py "Message text here"

This script reads 'CFD3_TELEGRAM'/'token' and 'CFD3_TELEGRAM'/'chat' from keyring.
It sends a single sendMessage request and prints detailed results.

Note: ensure your virtualenv has 'requests' installed, or run with system python that has requests.
"""
import sys
import time
import keyring
import requests


def get_credentials():
    token = keyring.get_password('CFD3_TELEGRAM', 'token')
    chat = keyring.get_password('CFD3_TELEGRAM', 'chat')
    return token, chat


def send_message(token, chat, text):
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = {'chat_id': chat, 'text': text}
    try:
        r = requests.post(url, data=data, timeout=15)
        try:
            j = r.json()
        except Exception:
            j = {'text': r.text}
        return r.status_code, j
    except Exception as e:
        return None, {'error': str(e)}


def main():
    if len(sys.argv) < 2:
        print('Usage: python scripts/test_telegram_send.py "Message text"')
        sys.exit(2)
    text = sys.argv[1]
    token, chat = get_credentials()
    if not token or not chat:
        print('Missing Telegram credentials in keyring. Use scripts/keyring_helpers.py to set CFD3_TELEGRAM token and chat.')
        sys.exit(3)
    print('Sending test message to chat:', chat)
    status, body = send_message(token, chat, text)
    print('HTTP status:', status)
    print('Response body:', body)
    if status == 200 and isinstance(body, dict) and body.get('ok'):
        print('Send succeeded.')
        sys.exit(0)
    else:
        print('Send failed — see response above for details.')
        sys.exit(1)


if __name__ == '__main__':
    main()
