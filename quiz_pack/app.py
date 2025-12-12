"""
Streamlit Frontend for Korean Grammar Quiz System
日本語UI対応版（ラベルローカライズ + 詳細採点表示）
"""

import streamlit as st
import requests
try:
    from quiz_pack.backend.judge import grade_answer  # 局所採点フォールバック
except ModuleNotFoundError:
    grade_answer = None

# 日本語 → 内部キー変換マッピング
TYPE_MAP = {
    "選択問題": "mcq",
    "穴埋め問題": "cloze",
    "作文問題": "writing",
}

st.set_page_config(page_title="韓国語文法トレーニング", layout="wide")

st.title("🇰🇷 韓国語文法 練習アプリ")
st.caption("文法解説を読んで、練習問題に挑戦してみましょう！")

# Sidebar 設定
st.sidebar.header("⚙️ 設定")
api_url = st.sidebar.text_input("API サーバーURL", "http://localhost:8002/api/quiz")
tone = st.sidebar.radio("トーン（話し方）を選んでください", ["standard", "osaka"], index=0)
unit = st.sidebar.selectbox("文法を選んでください", ["19", "20", "21", "22", "23", "24", "25"], index=0)

problem_types_jp = st.sidebar.multiselect(
    "出題形式を選んでください",
    ["選択問題", "穴埋め問題", "作文問題"],
    default=["選択問題"]
)
problem_types = [TYPE_MAP[t] for t in problem_types_jp]

tab1, tab2 = st.tabs(["📘 文法解説", "🧩 問題に挑戦"])

# ======== 文法解説タブ ========
with tab1:
    st.subheader(f"文法{unit} の解説（{ '大阪弁' if tone=='osaka' else '標準語' }トーン）")
    explain_url = api_url.replace("/api/quiz", "/api/explain")
    try:
        res = requests.post(explain_url, json={"unit": unit, "tone": tone}, timeout=10)
        if res.status_code == 200:
            data = res.json()
            st.markdown(data.get("text", "解説を取得できませんでした。"), unsafe_allow_html=True)
        else:
            st.error(f"サーバーエラー: {res.status_code}")
    except Exception as e:
        st.error(f"API接続に失敗しました: {e}")

# ======== 問題タブ ========
with tab2:
    st.subheader(f"文法{unit} の練習問題")
    if st.button("🎯 問題を生成"):
        try:
            res = requests.post(api_url, json={"unit": unit, "tone": tone}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                st.success("問題を取得しました！")

                # 各タイプごとに出題
                for t in problem_types:
                    section_title = [k for k, v in TYPE_MAP.items() if v == t][0]
                    st.markdown(f"### 🧠 {section_title}")
                    qlist = data.get(t, [])
                    if not qlist:
                        st.info("問題がまだありません。")
                        continue
                    for idx, q in enumerate(qlist, 1):
                        # 問題文キー（MCQ/Cloze は question、Writing は instruction）
                        statement = q.get("question") or q.get("instruction") or ""
                        st.markdown(f"**Q{idx}. {statement}**")

                        # 選択問題
                        if t == "mcq":
                            options = q.get("choices", [])
                            answer = q.get("answer", "")
                            user = st.radio("答えを選んでください：", options, key=f"{unit}_{t}_{idx}")
                            if st.button(f"採点_{unit}_{t}_{idx}"):
                                grade_url = api_url.replace("/api/quiz", "/api/grade")
                                try:
                                    gres = requests.post(grade_url, json={"user_answer": user, "correct_answer": answer}, timeout=8)
                                    result = gres.json().get("result", {}) if gres.ok else {}
                                except Exception:
                                    # ローカルフォールバック
                                    if grade_answer:
                                        result = grade_answer(user, answer)
                                    else:
                                        result = {"correct": user == answer, "score": 1.0 if user==answer else 0.0, "mode": "fallback"}
                                score_val = result.get("score", 0.0)
                                mode = result.get("mode", "")
                                if score_val >= 0.95:
                                    st.success(f"⭕ 正解！({mode})")
                                elif score_val >= 0.85:
                                    st.warning(f"🟡 語幹一致({mode})")
                                elif score_val >= 0.7:
                                    st.info(f"🟠 部分一致({mode})")
                                else:
                                    st.error(f"❌ 不正解 ({mode or '再確認'})")
                                st.caption(f"正答: {answer}")
                                if q.get("explanation"):
                                    st.write(q["explanation"])

                        # 穴埋め問題
                        elif t == "cloze":
                            user = st.text_input("空欄に入る語/形を入力：", key=f"{unit}_{t}_{idx}")
                            answer = q.get("answer", "")
                            if st.button(f"採点_{unit}_{t}_{idx}"):
                                grade_url = api_url.replace("/api/quiz", "/api/grade")
                                try:
                                    gres = requests.post(grade_url, json={"user_answer": user, "correct_answer": answer}, timeout=8)
                                    result = gres.json().get("result", {}) if gres.ok else {}
                                except Exception:
                                    result = grade_answer(user, answer) if grade_answer else {"correct": user==answer, "score": 1.0 if user==answer else 0.0, "mode": "fallback"}
                                score_val = result.get("score", 0.0)
                                mode = result.get("mode", "")
                                if score_val >= 0.95:
                                    st.success(f"⭕ 正解！({mode})")
                                elif score_val >= 0.85:
                                    st.warning(f"🟡 語幹一致({mode})")
                                elif score_val >= 0.7:
                                    st.info(f"🟠 部分一致({mode})")
                                else:
                                    st.error(f"❌ 不正解 ({mode or '再確認'})")
                                st.caption(f"正答: {answer}")
                                meta_line = []
                                if q.get("pattern"):
                                    meta_line.append(f"Pattern: {q['pattern']}")
                                if q.get("concept"):
                                    meta_line.append(f"Concept: {q['concept']}")
                                if meta_line:
                                    st.caption(" / ".join(meta_line))
                                if q.get("distractors"):
                                    st.caption("よく間違う候補: " + ", ".join(q["distractors"]))
                                if q.get("explanation"):
                                    st.write(q["explanation"])

                        # 作文問題
                        elif t == "writing":
                            answer = q.get("answer", "")
                            pool = q.get("word_pool") or q.get("wordPool") or []
                            if pool:
                                st.caption("語群: " + " ・ ".join(pool))
                            user = st.text_area("日本語を見て韓国語で文を作りましょう：", key=f"{unit}_{t}_{idx}")
                            if st.button(f"採点_{unit}_{t}_{idx}"):
                                grade_url = api_url.replace("/api/quiz", "/api/grade")
                                try:
                                    gres = requests.post(grade_url, json={"user_answer": user, "correct_answer": answer}, timeout=8)
                                    result = gres.json().get("result", {}) if gres.ok else {}
                                except Exception:
                                    result = grade_answer(user, answer) if grade_answer else {"correct": user==answer, "score": 1.0 if user==answer else 0.0, "mode": "fallback"}
                                score_val = result.get("score", 0.0)
                                mode = result.get("mode", "")
                                if score_val >= 0.95:
                                    st.success(f"⭕ 完璧！({mode})")
                                elif score_val >= 0.85:
                                    st.warning(f"🟡 語幹一致({mode})")
                                elif score_val >= 0.7:
                                    st.info(f"🟠 部分一致({mode})")
                                else:
                                    st.error(f"❌ もう一度確認しましょう ({mode or '再確認'})")
                                st.caption(f"模範解答: {answer}")
                                if q.get("explanation"):
                                    st.write(q["explanation"])
            else:
                st.error(f"APIエラー: {res.status_code}")
        except Exception as e:
            st.error(f"サーバー通信エラー: {e}")
