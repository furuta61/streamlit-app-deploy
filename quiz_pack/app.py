"""Streamlit UI

3つの解説モード（標準・発展・大阪弁）と、3つの問題形式（概念チェック・4択・作文）を
`rules.py` の統合マスターデータから表示します。
"""

from __future__ import annotations

import textwrap
from typing import Dict, List, Tuple

import streamlit as st

from quiz_pack.backend.rules import rules


def _norm(text: str) -> str:
    return textwrap.dedent(str(text or "")).strip()


def _extract_adv_and_concept(standard_text: str) -> Tuple[str, str]:
    """standard から「発展(+α)」行と「🧩 概念チェック」ブロックを拾う（最小実装）。"""
    lines = _norm(standard_text).splitlines()
    adv_lines: List[str] = []
    concept_lines: List[str] = []
    in_concept = False
    for line in lines:
        stripped = line.strip()
        if "🧩" in stripped:
            in_concept = True
            concept_lines.append(line)
            continue
        if in_concept:
            concept_lines.append(line)
            continue
        if stripped.startswith("発展"):
            adv_lines.append(line)
    return ("\n".join(adv_lines).strip(), "\n".join(concept_lines).strip())


st.set_page_config(page_title="韓国語文法トレーニング", layout="wide")

st.title("🇰🇷 韓国語文法 練習アプリ")

# Sidebar: 文法選択
unit_keys = sorted(rules.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))
unit = st.sidebar.selectbox("単元を選択", unit_keys, index=0)

# 解説表示（タブ切り替え）
tab_std, tab_adv, tab_osaka = st.tabs(["📘 基本解説", "💡 発展学習 (+α)", "🐙 大阪弁"])
with tab_std:
    st.markdown(_norm(rules[unit].get("standard", "")))
with tab_adv:
    st.info("発展的なルールや例外を学ぼう！")
    adv_text, concept_text = _extract_adv_and_concept(rules[unit].get("standard", ""))
    if adv_text:
        st.markdown(_norm(adv_text))
    if concept_text:
        st.markdown(_norm(concept_text))
with tab_osaka:
    st.markdown(_norm(rules[unit].get("osaka", "")))

# 問題モード選択
mode = st.radio("問題形式", ["概念チェック", "4択問題", "作文問題"], horizontal=True)

if mode == "概念チェック":
    _, concept_text = _extract_adv_and_concept(rules[unit].get("standard", ""))
    if concept_text:
        st.markdown(_norm(concept_text))
    else:
        st.info("この単元の概念チェックは未登録です。")

elif mode == "4択問題":
    mcq: Dict = rules[unit].get("mcq") or {}
    if not mcq:
        st.info("この単元の4択問題は未登録です。")
    else:
        st.markdown(f"**{mcq.get('question','')}**")
        choices = mcq.get("choices") or []
        answer = mcq.get("answer")
        if choices:
            user_choice = st.radio("答えを選択", choices, key=f"mcq_{unit}")
            if st.button("採点"):
                if user_choice == answer:
                    st.success("正解")
                else:
                    st.error("不正解")
                st.caption(f"正答: {answer}")

elif mode == "作文問題":
    writing: Dict = rules[unit].get("writing") or {}
    if not writing:
        st.info("この単元の作文問題は未登録です。")
    else:
        st.markdown(f"**{writing.get('question','')}**")
        hint = writing.get("hint")
        if hint:
            st.caption(f"ヒント: {hint}")
        _ = st.text_area("回答", key=f"writing_{unit}")
        if st.button("模範解答を表示"):
            st.caption(f"模範解答: {writing.get('answer','')}")
