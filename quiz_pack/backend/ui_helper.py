# -*- coding: utf-8 -*-
"""UI helper: Streamlit front-end support functions.
Minimal wrappers for API calls and grading result rendering.
"""
from __future__ import annotations
import requests
import streamlit as st
from typing import Any, Dict, List

def call_api(url: str, payload: Dict[str, Any]) -> Dict[str, Any] | None:
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.ok:
            ct = resp.headers.get('content-type','')
            if 'application/json' in ct:
                return resp.json()
        st.warning(f"API呼び出し失敗: {resp.status_code}")
    except Exception as e:
        st.error(f"API呼び出しエラー: {e}")
    return None

def grade_answer(api_base: str, user_answer: str, correct_answer: str) -> bool:
    """簡易採点: 正誤を直接比較。将来 /api/grade 個別呼び出しに差し替え可能。"""
    if user_answer is None:
        return False
    return str(user_answer).strip() == str(correct_answer).strip()

def render_result(is_correct: bool):
    if is_correct:
        st.success("✅ 正解です！")
    else:
        st.error("❌ 不正解です。")

def grade_mcq(api_base: str, unit: str, tone: str, question: str, selected: str) -> Dict[str, Any] | None:
    """/api/grade を1問分だけ呼び出して結果を返す。
    Back-end の /api/grade は items(list) を受け取るので単一要素で包む。
    戻り値: {'isCorrect': bool, 'correctAnswer': str, 'raw': full_response_dict}
    """
    try:
        grade_url = api_base.replace('/api/quiz', '/api/grade') if '/api/quiz' in api_base else api_base.rstrip('/') + '/grade'
        payload = {
            'unit': unit,
            'tone': tone,
            'items': [
                {'question': question, 'selected': selected}
            ]
        }
        resp = requests.post(grade_url, json=payload, timeout=10)
        if not resp.ok:
            st.warning(f"採点API失敗: {resp.status_code}")
            return None
        data = resp.json()
        results: List[Dict[str, Any]] = data.get('results', []) if isinstance(data, dict) else []
        if not results:
            return None
        r0 = results[0]
        return {
            'isCorrect': r0.get('isCorrect', False),
            'correctAnswer': r0.get('correctAnswer'),
            'raw': data
        }
    except Exception as e:
        st.error(f"採点APIエラー: {e}")
        return None

__all__ = ["call_api","grade_answer","render_result","grade_mcq"]
