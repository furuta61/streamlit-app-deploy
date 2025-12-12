# -- coding: utf-8 --
# 🇰🇷 韓国語文法学習アプリ（基礎＋発展＋練習問題）
import streamlit as st
import requests

st.set_page_config(page_title="韓国語文法学習", layout="wide")

# --- サイドバー設定 ---
st.sidebar.header("⚙️ 設定")
api_base = st.sidebar.text_input("API URL", "http://localhost:8002")
unit = st.sidebar.selectbox("📖 文法を選択", ["19", "20", "21", "22", "23", "24", "25"])
tone = st.sidebar.radio("🗣 トーン", ["standard", "osaka"], horizontal=True)

st.title("🇰🇷 韓国語文法 学習アプリ（基礎＋発展＋練習）")

# --- API呼び出し共通関数 ---
def fetch_explain():
    try:
        res = requests.post(f"{api_base}/api/explain", json={"unit": unit, "tone": tone})
        data = res.json()
        return data.get("text", "⚠️ 解説が取得できませんでした。")
    except Exception as e:
        return f"⚠️ API呼び出しエラー: {e}"


def fetch_exercise():
    try:
        res = requests.post(f"{api_base}/api/exercise", json={"unit": unit, "tone": tone})
        data = res.json()
        return data.get("items", [])
    except Exception:
        return []

# --- 基礎解説 ---
st.subheader(f"📘 文法{unit} 解説（{tone}）")
st.markdown(fetch_explain(), unsafe_allow_html=True)

# --- 発展解説 ---
st.markdown("---")
st.subheader("💡 発展解説（国立国語院・東京外国語大学 参考）")
st.markdown(
    """
以下は国立国語院（한국어문법 통합자료）および東京外国語大学『朝鮮語文法モジュール』を参考にした補足情報です。
※ 実際の出典要約は rules.py に統合し、tone 切替により大阪弁／標準語でのニュアンス比較が可能です。
""",
    unsafe_allow_html=True,
)

# --- 練習問題 ---
st.markdown("---")
st.subheader("🧩 練習問題（3問）")

questions = fetch_exercise()
if not questions:
    st.info("この単元にはまだ練習問題が登録されていません。")
else:
    for i, q in enumerate(questions[:3], 1):
        st.markdown(f"**Q{i}. {q['question']}**")
        choices = q.get("choices", [])
        if choices:
            for c in choices:
                st.markdown(f"- {c}")
        st.markdown("---")

st.caption("安定・軽量版 / 採点・印刷機能なし。将来拡張（採点/印刷/PDF）は容易です。")
