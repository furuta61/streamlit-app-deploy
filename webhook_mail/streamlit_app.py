import os
import streamlit as st
import requests

# ================== API接続先自動判定 ==================
# PUBLIC_BASE_URL が環境変数に設定されている場合はそのホストを利用。
# 未設定の場合はローカルFastAPIを前提にしたフォールバック。
PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/"))
if PUBLIC_BASE_URL:
    API_URL = f"{PUBLIC_BASE_URL}/analyze/image"
else:
    # 一時的に Cloudflare URL を直接指定（Secrets 未設定時の緊急対応）
    API_URL = "https://elizabeth-chips-strength-rooms.trycloudflare.com/analyze/image"

st.caption(f"API_URL = {API_URL}")

st.set_page_config(page_title="CFD3_AutoSystem IFD 自動生成（テスト版）")

st.header("📈 CFD3_AutoSystem — IFD 自動生成（テスト版）")

uploaded = st.file_uploader("スクショ画像をアップロード（PNG / JPG）", type=["png","jpg","jpeg"])

if uploaded is not None:
    st.image(uploaded, caption="アップロードされた画像", use_column_width=True)

    if st.button("AI解析を実行する"):
        # 画像をバイトに変換
        img_bytes = uploaded.getvalue()

        # FastAPI へ送信する multipart/form-data
        files = {
            "file": (
                uploaded.name,
                img_bytes,
                uploaded.type
            )
        }

        with st.spinner("FastAPI へ送信 → Vision解析中..."):
            # POST送信
            res = requests.post(API_URL, files=files)

        st.write("---")
        st.subheader("🧠 生レスポンス")
        st.code(res.text)

        if res.status_code == 200:
            data = res.json()

            st.subheader("🔍 画像AI解析結果")
            st.json(data.get("analysis"))

            st.subheader("📦 IFD 自動生成結果")
            st.json(data.get("ifd"))

            # --- 日本語IFDテーブルをレスポンシブ表示 ---
            if "ifd_markdown" in data:
                st.subheader("📊 日本語IFDテーブル（スマホ対応）")
                st.markdown(
                    """
                    <style>
                    /* 全体レイアウトの調整 */
                    .block-container {
                        padding-top: 0.5rem;
                        padding-bottom: 0.5rem;
                        padding-left: 0.8rem;
                        padding-right: 0.8rem;
                        max-width: 100%;
                    }

                    /* 表全体の余白・サイズ */
                    table {
                        width: 100%;
                        border-collapse: collapse;
                        font-size: 14px;
                        margin-top: 8px;
                        margin-bottom: 8px;
                    }

                    th, td {
                        border: 1px solid #ddd;
                        text-align: center;
                        padding: 6px;
                    }

                    th {
                        background-color: #f4f4f4;
                        font-weight: bold;
                    }

                    /* スマホ向け最適化 */
                    @media (max-width: 768px) {
                        table {
                            font-size: 12px;
                            margin: 0;
                        }
                        th, td {
                            padding: 4px;
                        }
                        .block-container {
                            padding: 0.4rem;
                        }
                    }
                    </style>
                    """,
                    unsafe_allow_html=True
                )
                st.markdown(data["ifd_markdown"], unsafe_allow_html=True)
        else:
            st.error(f"FastAPI 側エラー: {res.status_code}")
