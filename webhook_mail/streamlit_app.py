import streamlit as st
import os, sys
import requests
import json
import pandas as pd

# Optional Sheets imports
try:
    from googleapiclient.discovery import build
    from google.oauth2 import service_account
    SHEETS_AVAILABLE = True
except Exception:
    SHEETS_AVAILABLE = False

# --- Cloud / Local 両対応インポート ---
try:
    # ローカルで起動する場合
    from webhook_mail.main import analyze_image_with_ai
except ModuleNotFoundError:
    # Streamlit Cloud環境では親ディレクトリを検索パスに追加して再インポート
    current_dir = os.path.dirname(__file__)
    parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
    sys.path.append(parent_dir)
    import main  # webhook_mail.main ではなく main.py を直接読む
    analyze_image_with_ai = main.analyze_image_with_ai

"""
API接続先の決定ルール:
- PUBLIC_BASE_URL が環境変数(Secrets)にあればそれを使用
- なければ Direct モード（Streamlit内で直接AI解析とIFD生成）
"""
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
USE_API = bool(PUBLIC_BASE_URL)
if USE_API:
    BASE = PUBLIC_BASE_URL
    API_URL = f"{BASE}/analyze/image"
    st.caption(f"Mode: API / API URL: {API_URL}")
else:
    st.caption("Mode: Direct (Streamlitが直接AI解析とIFD生成)")
    # manual30_ifd も同様にインポート
    try:
        import manual30_ifd
    except ModuleNotFoundError:
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        import manual30_ifd

st.set_page_config(page_title="CFD3_AutoSystem IFD 自動生成（テスト版）")

st.header("📈 CFD3_AutoSystem — IFD 自動生成（テスト版）")

uploaded = st.file_uploader("スクショ画像をアップロード（PNG / JPG）", type=["png","jpg","jpeg"])

if uploaded is not None:
    st.image(uploaded, caption="アップロードされた画像", use_column_width=True)

    if st.button("AI解析を実行する"):
        # 画像をバイトに変換
        img_bytes = uploaded.getvalue()

        if USE_API:
            # FastAPI へ送信する multipart/form-data
            files = {
                "file": (
                    uploaded.name,
                    img_bytes,
                    uploaded.type
                )
            }

            with st.spinner("FastAPI へ送信 → Vision解析中..."):
                res = requests.post(API_URL, files=files)

            st.write("---")
            st.subheader("🧠 生レスポンス")
            st.code(res.text)

            if res.status_code == 200:
                data = res.json()
            else:
                st.error(f"FastAPI 側エラー: {res.status_code}")
                data = None
        else:
            with st.spinner("Streamlit 直実行: Vision解析中..."):
                analysis = analyze_image_with_ai(img_bytes)

            st.write("---")
            st.subheader("🔍 画像AI解析結果")
            st.json(analysis)

            # IFD 生成
            symbol = (analysis.get("symbol") or "JP225").upper()
            direction = (analysis.get("direction") or "buy").lower()
            entry = analysis.get("entry")
            signal = (analysis.get("signal") or ("STRONG_GO" if int(analysis.get("confidence") or 0) >= 80 else "GO")).upper()

            if not entry:
                st.error("エントリー価格が取得できませんでした（Vision + OCR両方失敗）")
                data = None
            else:
                ifd = manual30_ifd.generate_ifd(symbol=symbol, direction=direction, entry=float(entry), signal=signal)

                # Markdownテーブル（webhook_mail.main と同一様式）
                order = ifd.get("orders", [{}])[0]
                trade_mode = ifd.get("trade_mode", "MANUAL_30M")
                lots = order.get("lots", 1)
                entry_price = order.get("entry_order", {}).get("price", entry)
                oco = order.get("ifd_legs", [{}])[0].get("oco", {})
                tp_price = oco.get("take_profit", {}).get("price", 0)
                sl_price = oco.get("stop_loss", {}).get("price", 0)
                direction_jp = "買い" if direction == "buy" else "売り"
                ifd_markdown = f"""
| trade_mode | 銘柄 | 方向 | entry_price | SL | TP1 | TP2 | order_type | 判定 | ニュースロック | 推奨度 | ロット | CUT条件 |
|-------------|------|------|--------------|------|------|------|-------------|--------|----------------|----------|--------|-----------|
| {trade_mode} | {symbol} | {direction_jp} | {entry_price:.1f} | {sl_price:.1f} | {tp_price:.1f} | - | 指値 | {signal} | false | ★★★★★ | {lots} | SMA25＜SMA75 または MACD＜Signal |
"""

                data = {
                    "status": "success",
                    "symbol": symbol,
                    "analysis": analysis,
                    "ifd": ifd,
                    "ifd_markdown": ifd_markdown,
                }

        if data:
            if USE_API:
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

# --- Google Sheets 履歴ビュー ---
st.markdown("---")
st.subheader("📜 Google Sheets 履歴（自動ログ）")

if st.button("最新ログを取得"):
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    sheet_id = os.getenv("SHEET_ID")
    if not SHEETS_AVAILABLE:
        st.warning("⚠️ google-api-python-client / google-auth が未インストールです。requirements.txt を確認してください。")
    elif not creds_json or not sheet_id:
        st.warning("⚠️ Google Sheets の設定がありません。SHEET_ID / GOOGLE_CREDENTIALS_JSON を設定してください。")
    else:
        try:
            creds = service_account.Credentials.from_service_account_info(
                json.loads(creds_json),
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
            )
            service = build("sheets", "v4", credentials=creds)
            result = service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range="Logs!A1:I200"
            ).execute()
            rows = result.get("values", [])
            if not rows or len(rows) < 2:
                st.info("まだログデータがありません。")
            else:
                # 1行目ヘッダーと仮定
                df = pd.DataFrame(rows[1:], columns=rows[0])
                st.dataframe(df, use_container_width=True)
                st.success(f"✅ {len(df)} 行のログを取得しました。")
        except Exception as e:
            st.error(f"Sheets読込エラー: {e}")
