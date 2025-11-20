import streamlit as st
import base64
import json
import os
from openai import OpenAI

# OpenAI API キーを環境変数またはStreamlit Secretsから取得
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")
if not api_key:
    st.error("⚠️ OPENAI_API_KEYが設定されていません。Streamlit Cloudの場合はSecretsに設定してください。")
    st.stop()

client = OpenAI(api_key=api_key)

# ======== API 状態チェック ==========
def check_openai_status() -> str:
    """OpenAI APIの状態を確認"""
    try:
        # 簡単なテストリクエスト
        test_response = client.models.list()
        if test_response:
            return "🟢 OpenAI API Online"
        else:
            return "🔴 OpenAI API Error"
    except Exception as e:
        return f"🔴 OpenAI API Offline: {str(e)[:50]}"

# ======== GPT Vision 価格抽出 ==========
def extract_prices_gpt(image_bytes):

    b64 = base64.b64encode(image_bytes).decode("utf-8")

    prompt = """
あなたは最高精度のトレード補助AIです。

このiPhoneスクショから日本225, NAS100, GER40, XAUUSD のBid値だけ抽出して下さい。

形式は必ず以下：

{
  "JP225": 48706.9,
  "NAS100": 24587.5,
  "GER40": 23172.6,
  "XAUUSD": 4084.04
}

数字以外は禁止。
"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ],
            }
        ],
    )

    txt = res.choices[0].message.content
    
    # コードブロック除去
    if txt.startswith("```"):
        lines = txt.split("\n")
        txt = "\n".join(lines[1:-1]).strip()
    
    return json.loads(txt)


# ======== IFD テーブル作成 ==========
def make_ifd_table(symbol, entry, signal, direction):

    direction_jp = "買い" if direction == "buy" else "売り"
    trade_mode = "FLEX"

    # ロット
    lot = 2 if signal == "GO" else 6

    # SL
    SL = entry - 3000 if direction == "buy" else entry + 3000

    # TP
    if signal == "GO":
        TP1 = entry + 700 if direction == "buy" else entry - 700
        TP2 = "-"
    else:
        TP1 = entry + 1000 if direction == "buy" else entry - 1000
        TP2 = entry + 2000 if direction == "buy" else entry - 2000

    md = f"""
| trade_mode | 銘柄   | 方向 | entry_price |    SL    |    TP1   |   TP2    | order_type | 判定        | 推奨度 | ロット | エラー |
|------------|--------|------|-------------|----------|----------|----------|------------|-------------|--------|--------|--------|
| {trade_mode} | {symbol} | {direction_jp} | {entry:.2f} | {SL:.2f} | {TP1:.2f} | {TP2} | 指値 | {signal} | ★★★★☆ | {lot} | - |
"""
    return md


# ======== Streamlit UI ==========
st.title("📈 CFD3_AutoSystem — IFD 自動生成")

# サイドバーにAPI状態を表示
with st.sidebar:
    st.markdown("### 🔍 システム状態")
    api_status = check_openai_status()
    st.markdown(f"**{api_status}**")
    st.markdown("---")
    st.markdown("**使い方:**")
    st.markdown("1. スクショをアップロード")
    st.markdown("2. IFD生成ボタンをクリック")
    st.markdown("3. 自動生成された表を確認")

uploaded = st.file_uploader("スクショ画像をアップロード（PNG推奨）", type=["png", "jpg", "jpeg"])

if uploaded:
    st.image(uploaded, caption="アップロードされたスクショ", use_column_width=True)
    
    # 各銘柄の方向とシグナルを選択
    st.subheader("🎯 トレード設定")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("**JP225**")
        jp225_dir = st.selectbox("方向", ["buy", "sell"], key="jp225_dir", index=1)
        jp225_sig = st.selectbox("シグナル", ["GO", "STRONG_GO"], key="jp225_sig", index=1)
    
    with col2:
        st.markdown("**NAS100**")
        nas100_dir = st.selectbox("方向", ["buy", "sell"], key="nas100_dir", index=0)
        nas100_sig = st.selectbox("シグナル", ["GO", "STRONG_GO"], key="nas100_sig", index=0)
    
    with col3:
        st.markdown("**GER40**")
        ger40_dir = st.selectbox("方向", ["buy", "sell"], key="ger40_dir", index=1)
        ger40_sig = st.selectbox("シグナル", ["GO", "STRONG_GO"], key="ger40_sig", index=1)
    
    with col4:
        st.markdown("**XAUUSD**")
        xauusd_dir = st.selectbox("方向", ["buy", "sell"], key="xauusd_dir", index=0)
        xauusd_sig = st.selectbox("シグナル", ["GO", "STRONG_GO"], key="xauusd_sig", index=0)

    if st.button("IFD を生成する"):
        with st.spinner("GPT Vision が価格を解析中…"):
            prices = extract_prices_gpt(uploaded.read())

        st.subheader("📊 抽出された価格")
        st.json(prices)

        st.subheader("🧾 IFD テーブル（自動生成）")

        commands = [
            ("JP225", jp225_dir, jp225_sig),
            ("NAS100", nas100_dir, nas100_sig),
            ("GER40", ger40_dir, ger40_sig),
            ("XAUUSD", xauusd_dir, xauusd_sig),
        ]

        # 各銘柄テーブルをMarkdownで表示
        for sym, direction, sig in commands:
            entry = prices[sym]
            md = make_ifd_table(sym, entry, sig, direction)
            st.markdown(md)
            st.markdown("---")
