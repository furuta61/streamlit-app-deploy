#!/usr/bin/env python3
"""
Quick helper: find a recent chat_id from bot updates and send a test message.

Usage:
  python3 scripts/test_telegram_quicksend.py "Your test message"

This avoids manual copy/paste of chat_id: it reads the bot token from keyring
('CFD3_TELEGRAM' / 'token'), fetches recent updates, picks the most recent
chat id, and sends the message. Use this after you have started a private chat
with the bot or posted one message in the target group.

Security: token is read from macOS Keychain via python-keyring; no token is
printed or stored in logs. Do NOT paste the token into chat.
"""
import sys
import keyring
import requests


def get_token():
    return keyring.get_password('CFD3_TELEGRAM', 'token')


def get_recent_chat_id(token):
    url = f'https://api.telegram.org/bot{token}/getUpdates'
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    j = r.json()
    # scan results from newest to oldest
    for u in reversed(j.get('result', [])):
        m = u.get('message') or u.get('channel_post') or u.get('edited_message')
        if not m:
            continue
        chat = m.get('chat', {})
        cid = chat.get('id')
        if cid is not None:
            return cid
    return None


def send_message(token, chat_id, text):
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    r = requests.post(url, data={'chat_id': chat_id, 'text': text}, timeout=10)
    return r.status_code, r.text


def main():
    if len(sys.argv) < 2:
        print('Usage: python3 scripts/test_telegram_quicksend.py "Message text"')
        sys.exit(2)
    text = sys.argv[1]
    token = get_token()
    if not token:
        print('ERROR: token not found in keyring: run scripts/keyring_helpers.py set CFD3_TELEGRAM token')
        sys.exit(3)
    try:
        cid = get_recent_chat_id(token)
    except Exception as e:
        print('ERROR fetching updates:', e)
        sys.exit(4)
    if not cid:
        print('No recent chat id found. Make sure you have started a private chat with the bot or posted a message in the group, then try again.')
        sys.exit(5)
    print('Found chat id (hidden): sending test message...')
    try:
        status, body = send_message(token, cid, text)
        print('HTTP status:', status)
        print('Response body:', body)
        if status == 200:
            print('Send succeeded.')
            sys.exit(0)
        else:
            print('Send failed — see response above')
            sys.exit(6)
    except Exception as e:
        print('ERROR sending message:', e)
        sys.exit(7)


if __name__ == '__main__':
    main()
