# -*- coding: utf-8 -*-
# 🇰🇷 韓国語文法 学習アプリ（基礎＋発展＋練習：最終安定版）
import streamlit as st
import requests

st.set_page_config(page_title="韓国語文法 学習アプリ", layout="wide")

st.title("🇰🇷 韓国語文法 学習アプリ（基礎＋発展＋練習）")
st.caption("💡 現在：軽量モード（RAG・AI検索なし）で起動中")

# -----------------------
# 🔧 サイドバー設定
# -----------------------
st.sidebar.header("⚙️ 設定")

# ✅ デフォルトは Render の URL にする
DEFAULT_API_BASE = "https://korean-grammar-api-2.onrender.com"

# ✅ セッションに API ベースURLがなければ、デフォルト値を入れる
if "api_base" not in st.session_state:
    st.session_state["api_base"] = DEFAULT_API_BASE

# ✅ API ベースURL を UI から入力できるようにする
api_base = st.sidebar.text_input("APIベースURL", value=st.session_state["api_base"])

# ✅ 入力値をセッションに保存（毎回更新されるように）
st.session_state["api_base"] = api_base

unit = st.sidebar.selectbox("📖 文法を選択", ["19", "20", "21", "22", "23", "24", "25"])
tone = st.sidebar.radio("🗣 トーン", ["standard", "osaka"])

# -----------------------
# 🧠 API呼び出し関数
# -----------------------
def fetch_explain():
    try:
        res = requests.post(f"{api_base}/api/explain", json={"unit": unit, "tone": tone})
        data = res.json()
        return data.get("text", "⚠️ データを取得できませんでした。")
    except Exception as e:
        return f"❌ API 呼び出しエラー: {e}"

def fetch_exercise(qtype: str):
    try:
        res = requests.post(f"{api_base}/api/exercise", json={"unit": unit, "tone": tone, "type": qtype})
        data = res.json()
        return data.get("items", [])
    except Exception as e:
        return f"❌ 練習問題の取得に失敗しました: {e}"

# -----------------------
# 🧩 メインUI構成（タブ分離）
# -----------------------
tabs = st.tabs(["📘 文法解説（基礎＋発展）", "🧩 練習問題"])

# -----------------------
# 📘 文法解説タブ
# -----------------------
with tabs[0]:
    st.subheader("📘 文法解説（基礎＋発展）")
    explain = fetch_explain()
    st.markdown(explain, unsafe_allow_html=True)

# -----------------------
# 🧩 練習問題タブ
# -----------------------
with tabs[1]:
    st.subheader("🧩 練習問題を選択して挑戦")
    qtype = st.radio(
        "出題形式を選んでください",
        ["① 四択問題", "② 穴埋め問題", "③ 概念理解問題", "④ 作文問題"]
    )

    # 問題タイプをAPI引数に変換
    type_map = {
        "① 四択問題": "mcq",
        "② 穴埋め問題": "cloze",
        "③ 概念理解問題": "concept",
        "④ 作文問題": "writing",
    }
    selected_type = type_map[qtype]

    # 問題取得
    items = fetch_exercise(selected_type)

    if isinstance(items, str):
        st.error(items)
    elif not items:
        st.warning("この単元には練習問題がまだ登録されていません。")
    else:
        st.success(f"{len(items)}問が見つかりました！頑張ってください 💪")

        for i, q in enumerate(items, start=1):
            st.markdown(f"### Q{i}. {q.get('question', '問題文なし')}")

            if selected_type == "mcq":
                choices = q.get("choices", [])
                user = st.radio("選択肢:", choices, key=f"mcq_{i}")
                if st.button(f"答えを表示（Q{i}）", key=f"mcq_ans_{i}"):
                    st.info(f"✅ 正解: {q.get('answer', '（不明）')}")

            elif selected_type == "cloze":
                ans = st.text_input("（　）に入る言葉を入力してください:", key=f"cloze_{i}")
                if st.button(f"答えを表示（Q{i}）", key=f"cloze_ans_{i}"):
                    st.info(f"✅ 正解: {q.get('answer', '')}")

            elif selected_type == "concept":
                st.write("次の（　）に入る正しい語を選びましょう。")
                choices = q.get("choices", [])
                user = st.radio("選択肢:", choices, key=f"concept_{i}")
                if st.button(f"答えを表示（Q{i}）", key=f"concept_ans_{i}"):
                    st.info(f"✅ 正解: {q.get('answer', '')}")

            elif selected_type == "writing":
                st.text_area("あなたの解答を入力してください:", key=f"write_{i}")
                if st.button(f"模範解答を見る（Q{i}）", key=f"write_ans_{i}"):
                    st.info(f"📝 模範解答: {q.get('answer', '')}")
