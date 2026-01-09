import streamlit as st
import requests

st.set_page_config(page_title="Korean Grammar (Local UI)", layout="wide")

API_BASE = st.sidebar.text_input("API Base URL", value="http://127.0.0.1:8000")

unit = st.sidebar.number_input("Unit", min_value=1, max_value=25, value=20, step=1)
dialect = st.sidebar.radio("Version", ["standard", "osaka"], index=0, horizontal=True)
level = st.sidebar.radio("Explain Level", ["basic", "advanced"], index=0, horizontal=True)

st.title("韓国語 文法 解説＋クイズ（ローカルUI）")

# ---- Grammar ----
st.subheader(f"文法 {unit}（{dialect} / {level}）")

try:
    r = requests.get(f"{API_BASE}/api/grammar/{unit}", params={"dialect": dialect, "level": level}, timeout=10)
    if r.status_code != 200:
        st.error(f"Grammar API error: {r.status_code} {r.text}")
    else:
        data = r.json()
        st.caption(f"source: {data.get('source')}")
        st.text_area("解説", value=data.get("content", ""), height=360)
except Exception as e:
    st.error(f"APIに接続できません: {e}")

st.divider()

# ---- Quiz ----
st.subheader("クイズ")

quiz = None
try:
    rq = requests.get(f"{API_BASE}/api/quiz/{unit}", params={"dialect": dialect, "level": level}, timeout=10)
    if rq.status_code != 200:
        st.error(f"Quiz GET error: {rq.status_code} {rq.text}")
    else:
        quiz = rq.json()
except Exception as e:
    st.error(f"Quiz APIに接続できません: {e}")

answers_payload = {"answers": []}

if quiz:
    for q in quiz["questions"]:
        st.markdown("---")
        st.markdown(q["prompt"].replace("\n", "  \n"))

        if q["qtype"] == "mcq":
            sel = st.radio(f"選択: {q['qid']}", q["choices"], key=q["qid"])
            answers_payload["answers"].append({"qid": q["qid"], "answer": sel})

        else:
            ans = st.text_input(f"回答: {q['qid']}", key=q["qid"])
            answers_payload["answers"].append({"qid": q["qid"], "answer": ans})

    if st.button("採点する（送信）", type="primary"):
        try:
            rp = requests.post(f"{API_BASE}/api/quiz/{unit}", json=answers_payload, timeout=10)
            if rp.status_code != 200:
                st.error(f"Quiz POST error: {rp.status_code} {rp.text}")
            else:
                res = rp.json()
                st.success(f"Score: {res['score']} / {res['total']}")
                for item in res["results"]:
                    st.write(item)
        except Exception as e:
            st.error(f"採点APIに接続できません: {e}")
