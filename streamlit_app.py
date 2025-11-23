import os
import streamlit as st
import requests

st.set_page_config(page_title="CFD3_AutoSystem IFD 自動生成（テスト版）")

st.title("📈 CFD3_AutoSystem — IFD 自動生成（テスト版）")

# ---- 接続モード ----
api_url = os.getenv("PUBLIC_BASE_URL", "").strip()
if api_url:
    mode = f"API Mode (接続先: {api_url})"
else:
    mode = "Direct Mode (Streamlitが直接AI解析とIFD生成)"
st.caption(f"Mode: {mode}")

# ---- ファイルアップロード ----
uploaded_file = st.file_uploader("スクショ画像をアップロード（PNG / JPG）", type=["png", "jpg", "jpeg"])

if uploaded_file:
    st.image(uploaded_file, caption="アップロードされた画像", use_column_width=True)

    # ---- API経由 or ローカル処理 ----
    if api_url:
        st.write("🔍 AI解析を実行中…")
        try:
            files = {"file": uploaded_file.getvalue()}
            response = requests.post(f"{api_url}/analyze/image", files=files, timeout=90)
            if response.status_code == 200:
                result = response.json()
                st.success("✅ AI解析が完了しました！")
                st.json(result)
            else:
                st.error(f"❌ APIエラー: {response.status_code}")
        except Exception as e:
            st.error(f"接続に失敗しました: {e}")
    else:
        st.warning("⚠️ 現在はDirectモードです（ローカルAPIを使用しません）。")

# ---- ヘルスチェック ----
st.header("🩺 システム ヘルスチェック")
if st.button("✅ 接続状態を確認する"):
    target = api_url or "http://localhost:8080"
    try:
        res = requests.get(f"{target}/health", timeout=10)
        st.json(res.json())
    except Exception as e:
        st.error(f"❌ 接続エラー: {e}")
        st.caption(f"確認URL: {target}/health")
