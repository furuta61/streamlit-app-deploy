# -*- coding: utf-8 -*-
"""ui_helper.py
UI 用の整形・ハイライト・サニタイズ補助関数。
"""
from __future__ import annotations
import re
from typing import List

HIGHLIGHT_PATTERNS = [r'-고 있다', r'-아/어 있다', r'-(으)시-', r'-겠-', r'-었-', r'-ㄹ 것이다']

SPAN_STYLE = 'background: #ffeaa7; padding:2px; border-radius:3px;'

def highlight_grammar(text: str) -> str:
    result = text
    for pat in HIGHLIGHT_PATTERNS:
        result = re.sub(pat, lambda m: f"<span style='{SPAN_STYLE}'>{m.group(0)}</span>", result)
    return result

def sanitize_user_answer(ans: str) -> str:
    if not ans:
        return ''
    # collapse whitespace
    cleaned = re.sub(r'\s+', ' ', ans.strip())
    # remove dangerous tags
    cleaned = re.sub(r'<(/?script|/?iframe|/?object)[^>]*>', '', cleaned, flags=re.I)
    return cleaned

def extract_snippets(doc: str, max_snippets: int = 3, min_len: int = 15) -> List[str]:
    sentences = re.split(r'[。!?]', doc)
    snippets = [s.strip() for s in sentences if len(s.strip()) >= min_len]
    return snippets[:max_snippets]

__all__ = [
    'highlight_grammar','sanitize_user_answer','extract_snippets'
]
