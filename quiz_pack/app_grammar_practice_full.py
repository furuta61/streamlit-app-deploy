# -- coding: utf-8 --
import streamlit as st
import requests

st.set_page_config(page_title="韓国語文法 学習（練習強化版）", layout="wide")

# -------------------
# サイドバー
# -------------------
st.sidebar.header("⚙️ 設定")
api_base = st.sidebar.text_input("API URL", "http://localhost:8002")
unit = st.sidebar.selectbox("📖 文法を選択", ["19","20","21","22","23","24","25"])
tone = st.sidebar.radio("🗣 トーン", ["standard","osaka"], horizontal=True)

st.title("🇰🇷 韓国語文法 学習アプリ（基礎＋発展＋練習 強化版）")

# -------------------
# API関数
# -------------------
def fetch_explain():
    try:
        res = requests.post(f"{api_base}/api/explain", json={"unit": unit, "tone": tone})
        data = res.json()
        return data.get("text", "⚠️ 解説が取得できません。")
    except Exception as e:
        return f"⚠️ APIエラー: {e}"


def fetch_quiz_lists():
    """フル問題バンク (/api/quiz) を利用して MCQ/Cloze/Writing をまとめて取得"""
    try:
        res = requests.post(f"{api_base}/api/quiz", json={"unit": unit, "tone": tone})
        data = res.json()
        return (
            data.get("mcq", []) or [],
            data.get("cloze", []) or [],
            data.get("writing", []) or [],
        )
    except Exception:
        return [], [], []

# -------------------
# 文法解説
# -------------------
st.subheader(f"📘 文法{unit} 解説（{tone}）")
st.markdown(fetch_explain(), unsafe_allow_html=True)

# -------------------
# 発展解説
# -------------------
st.markdown("---")
st.subheader("💡 発展解説（国立国語院・東京外国語大学 参考）")
st.markdown(
    """
国立国語院（한국어문법 통합자료）および
東京外国語大学『朝鮮語文法モジュール』を参考に、
使い分けや補足的な情報を解説しています。
"""
)

# -------------------
# 練習問題セクション
# -------------------
st.markdown("---")
st.subheader("🧩 練習問題")
mode = st.radio("問題タイプを選んでください：", ["4択", "穴埋め", "作文"], horizontal=True)

mcq_list, cloze_list, writing_list = fetch_quiz_lists()

if not (mcq_list or cloze_list or writing_list):
    st.warning("この単元にはまだ問題が登録されていません。")
else:
    # --- 4択 ---
    if mode == "4択":
        mcqs = (mcq_list or [])[:5]  # 最大5問
        for i, q in enumerate(mcqs, 1):
            st.markdown(f"**Q{i}. {q.get('question','')}**")
            answer = q.get("answer", "")
            explanation = q.get("explanation", "")
            choices = q.get("choices", [])
            user_choice = st.radio("選択肢:", choices, key=f"mcq_{i}")
            if st.button(f"答えを見る_{i}"):
                if user_choice == answer:
                    st.success(f"✅ 正解！ → {answer}")
                else:
                    st.error(f"❌ 不正解。正解は「{answer}」です。")
                if explanation:
                    st.info(f"💡 解説: {explanation[:250]}...")

    # --- 穴埋め ---
    elif mode == "穴埋め":
        # ★最大2問に変更（1問でも可）
        clozes = [q for q in (cloze_list or []) if "____" in q.get("question", "")][:2]
        for i, q in enumerate(clozes, 1):
            st.markdown(f"**Q{i}. {q.get('question','')}**")
            user_input = st.text_input("答えを入力してください:", key=f"cloze_{i}")
            if st.button(f"答えを見る_cloze_{i}"):
                st.success(f"正解: {q.get('answer','')}")
                if q.get("original"):
                    st.info(f"💡 原文: {q['original']}")
                exp = q.get("explanation", "")
                if exp:
                    st.caption(exp[:200])
        if not clozes:
            st.info("この文法項目には穴埋め問題が登録されていません。")

    # --- 作文 ---
    elif mode == "作文":
        writings = (writing_list or [])[:3]  # 最大3問
        for i, q in enumerate(writings, 1):
            st.markdown(f"**Q{i}. {q.get('instruction','')}**")
            st.text_area("あなたの解答", key=f"write_{i}")
            if st.button(f"模範解答を見る_{i}"):
                st.success(f"模範解答: {q.get('answer','')}")
                exp = q.get("explanation", "")
                if exp:
                    st.caption(exp[:200])

st.caption("安定版（採点/印刷なし）: 4択 最大5問 / 穴埋め 最大2問 / 作文 最大3問。大阪弁/標準語切替に対応。")
