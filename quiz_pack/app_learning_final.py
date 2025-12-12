# -- coding: utf-8 --
import streamlit as st
import requests

st.set_page_config(page_title="韓国語文法 学習アプリ（基礎・発展・練習）", layout="wide")

# ---------------------------
# Sidebar Settings
# ---------------------------
st.sidebar.header("⚙️ 設定")
api_base = st.sidebar.text_input("API URL", "http://localhost:8002")
unit = st.sidebar.selectbox("📖 文法を選択", ["19", "20", "21", "22", "23", "24", "25"])
tone = st.sidebar.radio("🗣 トーン", ["standard", "osaka"])

st.title("🇰🇷 韓国語文法 学習アプリ（基礎＋発展＋練習）")

# ---------------------------
# Helper Functions
# ---------------------------

def fetch_explain():
    try:
        res = requests.post(f"{api_base}/api/explain", json={"unit": unit, "tone": tone})
        return res.json().get("text", "")
    except Exception as e:
        return f"⚠️ APIエラー: {e}"


def fetch_exercise():
    try:
        res = requests.post(f"{api_base}/api/exercise", json={"unit": unit, "tone": tone})
        return res.json().get("items", [])
    except Exception:
        return []

# ---------------------------
# Tab Layout
# ---------------------------

tab1, tab2 = st.tabs(["📘 文法・発展解説", "🧩 練習問題"])

# ===========================
# 📘 文法＋発展タブ
# ===========================
with tab1:
    st.subheader(f"📘 文法{unit} 解説（{tone}）")

    text = fetch_explain()
    if not text:
        st.warning("この文法の解説データが見つかりません。")
    else:
        # 文法解説をそのまま表示（穴埋めなどは含まない）
        st.markdown(text, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("💡 発展解説（国立国語院・東京外国語大学 参考）")
    st.markdown(
        """
国立国語院（한국어문법 통합자료）および  
東京外国語大学『朝鮮語文法モジュール』の情報を基に、  
使い分け・用法の詳細・学術的背景を補足しています。
"""
    )

# ===========================
# 🧩 練習問題タブ
# ===========================
with tab2:
    st.subheader("🧩 練習モードを選択してください")
    mode = st.radio("練習タイプ：", ["4択問題", "穴埋め問題（概念理解）", "作文問題"], horizontal=True)
    st.markdown("---")

    # fetch questions
    questions = fetch_exercise()

    if not questions:
        st.info("この文法にはまだ練習問題が登録されていません。")
    else:
        # 4択
        if mode == "4択問題":
            st.markdown("### ✅ 4択練習")
            mcqs = [q for q in questions if "choices" in q][:5]
            for i, q in enumerate(mcqs, 1):
                st.markdown(f"**Q{i}. {q['question']}**")
                options = q.get("choices", [])
                for c in options:
                    st.markdown(f"- {c}")
                if st.button(f"答えを見る_{i}"):
                    st.success(f"✅ 正解: {q['answer']}")
                    st.caption(f"{q.get('explanation', '')[:200]}")

        # 穴埋め：学習目標の概念理解
        elif mode == "穴埋め問題（概念理解）":
            st.markdown("### ✏️ 学習目標に関する概念チェック")
            clozes = [
                {
                    "question": "① -(으)ㄹ까요? は相手の（　　　　）・意見を尋ねたり、（　　　　）場面で使う表現です。ただし、主語が（　　　　）の場合は、（　　　　）や推量の意味を表します。",
                    "choices": ["疑問", "誘う", "意向", "願望", "主張", "命令", "1人称", "2人称", "3人称"],
                    "answer": ["意見", "誘う", "3人称", "推量"],
                },
                {
                    "question": "② 「-(고) 있다」は動作の（　　　　）や（　　　　）を表す表現です。",
                    "choices": ["進行", "習慣", "完了", "結果", "推測"],
                    "answer": ["進行", "習慣"],
                },
            ][:2]
            for i, q in enumerate(clozes, 1):
                st.markdown(f"**Q{i}. {q['question']}**")
                st.markdown("選択肢: " + "　".join(q["choices"]))
                if st.button(f"答えを見る_cloze_{i}"):
                    st.success("✅ 正解: " + "・".join(q["answer"]))

        # 作文
        elif mode == "作文問題":
            st.markdown("### 🗒 作文練習")
            writings = [q for q in questions if "instruction" in q][:3]
            for i, q in enumerate(writings, 1):
                st.markdown(f"**Q{i}. {q['instruction']}**")
                st.text_area("あなたの答えを入力してください：", key=f"write_{i}")
                if st.button(f"模範解答を見る_{i}"):
                    st.success(f"模範解答: {q['answer']}")
                    st.caption(q.get("explanation", "")[:200])
