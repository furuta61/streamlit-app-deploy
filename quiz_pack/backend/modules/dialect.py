# -*- coding: utf-8 -*-
"""dialect.py
大阪弁変換などトーン変換関連。
"""
from __future__ import annotations
import re
from typing import List

KR_RE = re.compile(r"[가-힣]")

REPLACEMENTS = [
    (r"しましょう", "しよか"),
    (r"ませんでした", "へんかった"),
    (r"ません", "へん"),
    (r"ですか\?", "や？"),
    (r"ですか", "や？"),
    (r"です。", "やで。"),
    (r"です$", "や"),
    (r"です", "や"),
    (r"ます。", "ますよ。"),
    (r"ます$", "ますよ"),
    (r"でしょうか", "やろか"),
    (r"でしょう", "やろ"),
    (r"ね。", "やな。"),
    (r"ね、", "やな、"),
    (r"よ。", "やで。"),
    (r"よ、", "やで、"),
]

def to_osaka(text: str) -> str:
    if not text:
        return text
    s = text
    try:
        for pat, rep in REPLACEMENTS:
            s = re.sub(pat, rep, s)
        lines = s.splitlines()
        out: List[str] = []
        for l in lines:
            if not l.strip():
                out.append(l); continue
            if l.strip().startswith('#') or KR_RE.search(l):  # 見出しや韓国語行は無変換
                out.append(l); continue
            if re.search(r'[。.!？?]$|やで$|やな$|やろ$|へん$|しよか$|してや$|ますよ$', l):
                out.append(l)
            else:
                out.append(l + ' やで')
        s = '\n'.join(out)
    except Exception:
        return text
    return s

__all__ = ['to_osaka']
