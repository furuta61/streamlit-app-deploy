import os
import io
import base64
import json
from datetime import datetime

import streamlit as st
from openai import OpenAI
from PIL import Image

# ==== OpenAI クライアント ====
# OPENAI_API_KEY は .env か環境変数に設定しておいてください
client = OpenAI()


def image_file_to_data_url(uploaded_file) -> str:
    """アップロード画像を data URL (base64) に変換"""
    img_bytes = uploaded_file.read()
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    return f"data:{uploaded_file.type};base64,{b64}"


def call_gpt_vision_for_ifd(image_data_url: str) -> dict:
    """
    GPT-4o-mini に画像を渡して IFD 情報を JSON で返してもらう。
    返り値は Python の dict にパース済み。
    """
    prompt = """
あなたは日本語のFX/CFD取引画面のスクリーンショットから
IFD注文に必要な情報を読み取るアシスタントです。

スクリーンショットから、以下の情報を推定して JSON で返してください：

- symbol: 通貨ペア / 銘柄名（例: "USD/JPY", "EUR/JPY", "日経225" など）
- side: "buy" または "sell"
- entry_price: エントリー価格（数値）
- take_profit: 利確(決済)価格（数値、分からなければ null）
- stop_loss: 損切り価格（数値、分からなければ null）
- size: 取引数量（数値、ロットなど。分からなければ null）
- raw_text: 画面から読み取った主な文字列（元情報ログ用）

必ず **JSON だけ** を返してください。
日本語の説明文は一切含めないでください。
数値として読めない値は null にしてください。
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url},
                    },
                ],
            }
        ],
        temperature=0.0,
    )

    content = response.choices[0].message.content
    # content は通常 str か、複数チャンクの場合は list なので両対応
    if isinstance(content, list):
        text = "".join([c.get("text", "") for c in content if isinstance(c, dict)])
    else:
        text = content

    # JSONとしてパース
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # JSONでなかった場合は raw_text として丸ごと格納
        data = {
            "symbol": None,
            "side": None,
            "entry_price": None,
            "take_profit": None,
            "stop_loss": None,
            "size": None,
            "raw_text": text,
        }
    return data


def save_ifd_log(ifd_data: dict, image_filename: str):
    """logs/ ディレクトリに IFD JSON を保存"""
    os.makedirs("logs", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.splitext(os.path.basename(image_filename))[0]
    path = os.path.join("logs", f"ifd_{base}_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ifd_data, f, ensure_ascii=False, indent=2)
    return path


def main():
    st.title("📈 CFD3_AutoSystem — ローカル版 IFD 自動生成（独立テスト用）")
    st.caption("Backend / Health チェックなしのシンプル直結版（ローカル専用）")

    # APIキー確認
    if not os.environ.get("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY が環境変数に設定されていません。.env かシェルで設定してください。")
        st.stop()

    st.subheader("1. スクショ画像をアップロード（PNG / JPG）")

    uploaded_file = st.file_uploader(
        "取引画面のスクリーンショットを選択してください",
        type=["png", "jpg", "jpeg"],
    )

    if uploaded_file is None:
        st.info("画像をアップロードすると解析できます。")
        return

    # 画像プレビュー
    st.image(uploaded_file, caption="アップロードされた画像", use_column_width=True)

    if st.button("🔍 画像から IFD を自動解析する"):
        with st.spinner("GPT-4o-mini で画像解析中…"):
            try:
                data_url = image_file_to_data_url(uploaded_file)
                ifd = call_gpt_vision_for_ifd(data_url)
            except Exception as e:
                st.error(f"AI解析中にエラーが発生しました: {e}")
                return

        st.success("解析完了！IFD候補を表示します。")

        # 主要フィールドを見やすく表示
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 📊 基本情報")
            st.write("**銘柄 (symbol)**:", ifd.get("symbol"))
            st.write("**方向 (side)**:", ifd.get("side"))
            st.write("**数量 (size)**:", ifd.get("size"))

        with col2:
            st.markdown("### 💰 価格情報")
            st.write("**エントリー (entry_price)**:", ifd.get("entry_price"))
            st.write("**利確 (take_profit)**:", ifd.get("take_profit"))
            st.write("**損切り (stop_loss)**:", ifd.get("stop_loss"))

        # 生データを表示
        st.markdown("### 🧾 生のJSONデータ")
        st.json(ifd)

        # ログ保存
        log_path = save_ifd_log(ifd, uploaded_file.name)
        st.info(f"IFD JSON をログとして保存しました: `{log_path}`")


if __name__ == "__main__":
    main()
