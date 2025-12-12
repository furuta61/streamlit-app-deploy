"""三分割タブUI + 採点 + 印刷機能
基礎 / 発展 / 穴埋め（練習）を分離表示し、各タブに HTML ダウンロードリンクを付与。
"""
# -- coding: utf-8 --
# 📘 三分割タブ構成（基礎・発展・練習）＋ 採点＋印刷ボタン
import streamlit as st
import requests
import base64

st.set_page_config(page_title="韓国語文法学習アプリ", layout="wide")

st.sidebar.header("⚙️ 設定")
api_base = st.sidebar.text_input("API URL", "http://localhost:8002")
unit = st.sidebar.selectbox("📖 文法を選択", ["19","20","21","22","23","24","25"])
tone = st.sidebar.radio("🗣 トーン", ["standard", "osaka"])

st.title("🇰🇷 韓国語文法 学習アプリ（基礎・発展・練習 + 採点・印刷対応）")

tabs = st.tabs(["📘 基礎解説", "💡 発展解説", "🧩 練習問題"])

# --------------------------
# 共通API呼び出し
# --------------------------
def fetch_explain(part=None):
    try:
        res = requests.post(f"{api_base}/api/explain", json={"unit": unit, "tone": tone})
        data = res.json()
        text = data.get("text", "")
        if part == "basic":
            return text.split("#### 💡 発展情報")[0]
        elif part == "advanced":
            parts = text.split("#### 💡 発展情報")
            return "#### 💡 発展情報" + parts[1].split("#### 🧩 穴埋め")[0]
        elif part == "practice":
            if "#### 🧩 穴埋め" in text:
                return "#### 🧩 穴埋め" + text.split("#### 🧩 穴埋め")[1]
            else:
                return "（この単元には穴埋め問題がありません）"
        else:
            return text
    except Exception as e:
        return f"⚠️ API呼び出しに失敗しました: {e}"

# --------------------------
# 採点API（/api/grade シンプル版）
# --------------------------
def grade_answer(user_answer, correct_answer):
    try:
        res = requests.post(f"{api_base}/api/grade", json={
            "user_answer": user_answer,
            "correct_answer": correct_answer
        })
        data = res.json()
        score = data.get("score", 0)
        mode = data.get("mode", "")
        return score, mode
    except Exception as e:
        return 0, f"エラー: {e}"

# --------------------------
# 印刷用HTML出力（ダウンロードリンク生成）
# --------------------------
def download_html(content, filename="explain.html"):
    b64 = base64.b64encode(content.encode()).decode()
    href = f'<a href="data:file/html;base64,{b64}" download="{filename}">🖨️ 印刷用に保存（HTML）</a>'
    st.markdown(href, unsafe_allow_html=True)

# --------------------------
# タブ: 基礎
# --------------------------
with tabs[0]:
    st.subheader("📘 基礎解説")
    html_basic = fetch_explain("basic")
    st.markdown(html_basic, unsafe_allow_html=True)
    download_html(html_basic, f"unit{unit}_basic.html")

# --------------------------
# タブ: 発展
# --------------------------
with tabs[1]:
    st.subheader("💡 発展解説（国立国語院・東京外国語大学 参考）")
    html_adv = fetch_explain("advanced")
    st.markdown(html_adv, unsafe_allow_html=True)
    download_html(html_adv, f"unit{unit}_advanced.html")

# --------------------------
# タブ: 練習（穴埋め + 採点）
# --------------------------
with tabs[2]:
    st.subheader("🧩 練習問題（穴埋め + 採点対応）")
    practice_text = fetch_explain("practice")
    st.markdown(practice_text, unsafe_allow_html=True)

    st.markdown("---")
    st.write("下のボックスに答えを入力して採点してみましょう。")
    user_answer = st.text_input("あなたの答えを入力:", "")
    correct_answer = st.text_input("正答（教師用・確認用）:", "")

    if st.button("採点する"):
        score, mode = grade_answer(user_answer, correct_answer)
        if score >= 0.9:
            st.success(f"✅ 正解！（モード: {mode}, スコア: {score:.2f}）")
        elif score >= 0.7:
            st.warning(f"🟡 ほぼ正解！（モード: {mode}, スコア: {score:.2f}）")
        else:
            st.error(f"❌ 間違い（モード: {mode}, スコア: {score:.2f}）")

    download_html(practice_text, f"unit{unit}_practice.html")

# --------------------------
# 利用ガイド / 起動手順
# --------------------------
with st.expander("ℹ️ 使い方 / 起動手順"):
    st.markdown(
        """\n**起動手順 (ターミナル):**\n```bash\nsource .venv/bin/activate\nstreamlit run quiz_pack/app_tabs.py --server.port 8535\n```\nブラウザで http://localhost:8535 を開いてください。\n\n| タブ | 内容 |\n|------|------|\n| 📘 基礎解説 | 各課の概要・形成・基本用法 |\n| 💡 発展解説 | 国立国語院・東外大の補足情報・使い分け |\n| 🧩 練習問題 | 穴埋め形式で理解確認 + 採点API連携 |\n\n**トーン切替:** standard / osaka を切り替えると解説文が方言調に変化します。\n**自動取得:** 文法番号を選ぶと /api/explain を呼び出して該当部分を抽出表示します。\n"""
    )
