# -*- coding: utf-8 -*-
"""morph.py
語幹抽出・活用関連の簡易ユーティリティ。
"""
from __future__ import annotations
import re
from typing import Optional

KR_RE = re.compile(r"[가-힣]")

L_STEM_RULES = """
## ㄹ語幹の活用ルール（体系的まとめ）
1) 母音語尾の前 → ㄹ維持 (살아요)
2) 子音語尾の前 → ㄹ脱落 (삽니다)
3) 으語尾の前 → ㄹ+으 脱落 (사세요)
4) ㄴ語尾の前 → ㄹ脱落 (사는)
5) (으)시 → ㄹ脱落 (사시다→사세요)
"""

def _to_dict_form_simple(s: str) -> str:
    """簡易: 해요体/丁寧体を辞書形（다）に変換。安全な範囲のみ。"""
    if not s or not KR_RE.search(s):
        return s
    t = s.strip()
    t = re.sub(r"[\.,!?；;。！？…]+$", "", t)
    special = {
        '가요': '가다', '와요': '오다', '봐요': '보다', '줘요': '주다', '돼요': '되다', '해요': '하다',
        '드려요': '드리다', '드렸어요': '드리다'
    }
    if t in special:
        return special[t]
    if t.endswith('해요'):
        return t[:-2] + '하다'
    if t.endswith('아요') or t.endswith('어요'):
        return t[:-2] + '다'
    if t.endswith('습니다') or t.endswith('ㅂ니다'):
        return t[:-3] + '다'
    if t.endswith('세요'):
        return t[:-2] + '다'
    if t.endswith('요'):
        return t[:-1] + '다'
    return t

def guess_stem(word: str) -> Optional[str]:
    """辞書形（다終止）から語幹推定。安全な最小版。"""
    if not word or not word.endswith('다'):
        return None
    stem = word[:-1]  # remove final '다' only
    return stem

__all__ = [
    'L_STEM_RULES', '_to_dict_form_simple', 'guess_stem'
]
