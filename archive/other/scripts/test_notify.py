#!/usr/bin/env python3
from dotenv import load_dotenv
import os
import json

load_dotenv()

NOTIFY_ON = [s.strip().upper() for s in os.getenv("NOTIFY_ON", "STRONG_GO").split(",") if s.strip()]
TEXT_KEYWORDS = [k.lower() for k in os.getenv("NOTIFY_TEXT_KEYWORDS", "STRONG_GO,GO,cross,交差,IFD").split(",") if k.strip()]


def would_notify(payload):
    # replicate logic from webhook_mail.main.should_notify
    try:
        if any(x in (s.upper() for s in NOTIFY_ON) for x in ['*', 'ALL']):
            return True
    except Exception:
        pass

    sig = (payload.get('signal') or "").strip().upper()
    if sig:
        if sig in NOTIFY_ON:
            return True

    text = (payload.get('text') or "").lower()
    for kw in TEXT_KEYWORDS:
        if kw and kw in text:
            return True

    d = payload.get('data') or {}
    if isinstance(d, dict):
        for v in d.values():
            try:
                if isinstance(v, str) and any(kw in v.lower() for kw in TEXT_KEYWORDS):
                    return True
            except Exception:
                continue

    try:
        dump = json.dumps(payload.get('data') or {}).lower()
        if any(kw in dump for kw in TEXT_KEYWORDS):
            return True
    except Exception:
        pass

    return False


TEST_CASES = [
    {'name': 'strong_go_signal', 'payload': {'symbol': 'XAUUSD', 'signal': 'STRONG_GO', 'text': '', 'data': {}}},
    {'name': 'go_signal', 'payload': {'symbol': 'JP225', 'signal': 'GO', 'text': '', 'data': {}}},
    {'name': 'text_contains_strong_go', 'payload': {'symbol': 'NAS100', 'signal': None, 'text': 'Price shows STRONG_GO on 4h', 'data': {}}},
    {'name': 'no_signal_no_text', 'payload': {'symbol': 'COPPER', 'signal': None, 'text': '', 'data': {}}},
    {'name': 'data_contains_keyword', 'payload': {'symbol': 'US30', 'signal': None, 'text': '', 'data': {'note': 'IFD suggested'}}},
]

if __name__ == '__main__':
    print(f"ENV NOTIFY_ON={NOTIFY_ON}")
    print(f"ENV TEXT_KEYWORDS={TEXT_KEYWORDS}\n")
    for tc in TEST_CASES:
        res = would_notify(tc['payload'])
        print(f"{tc['name']}: would_notify={res} payload={tc['payload']}")
