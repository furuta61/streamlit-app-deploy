import os
import streamlit as st
import requests
import sys
from pathlib import Path

# --- Directモード用：Vision+IFD 解析関数インポート試行 ---
_DIRECT_AVAILABLE = False
try:
    # ルートパスを追加
    ROOT = Path(__file__).resolve().parent
    sys.path.insert(0, str(ROOT))
    from main import analyze_image_with_ai  # type: ignore
    import manual30_ifd  # type: ignore
    _DIRECT_AVAILABLE = True
except Exception:
    _DIRECT_AVAILABLE = False

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
        if not _DIRECT_AVAILABLE:
            st.warning("⚠️ Directモード: 解析関数をインポートできませんでした。APIモードに切り替えるか backend を起動してください。")
        else:
            st.write("🔍 Directモードで Vision+IFD 解析を実行します…")
            try:
                img_bytes = uploaded_file.getvalue()
                analysis = analyze_image_with_ai(img_bytes)
                symbol = analysis.get("symbol") or "UNKNOWN"
                direction = analysis.get("direction") or "buy"
                signal = analysis.get("signal") or ("STRONG_GO" if (analysis.get("confidence") or 0) >= 80 else "GO")
                entry = analysis.get("entry")
                if entry:
                    try:
                        ifd = manual30_ifd.generate_ifd(symbol=symbol, direction=direction, entry=float(entry), signal=signal)
                    except Exception as e:
                        ifd = {"error": f"IFD生成失敗: {e}"}
                else:
                    ifd = {"error": "エントリー価格が取得できませんでした (Vision+OCR失敗)"}

                # Markdownテーブル整形
                md = ""
                try:
                    order = (ifd.get("orders") or [{}])[0]
                    trade_mode = ifd.get("trade_mode", "MANUAL_30M")
                    lots = order.get("lots", 1)
                    entry_price = order.get("entry_order", {}).get("price", entry) or entry
                    oco = order.get("ifd_legs", [{}])[0].get("oco", {})
                    tp_price = oco.get("take_profit", {}).get("price", 0) or 0
                    sl_price = oco.get("stop_loss", {}).get("price", 0) or 0
                    direction_jp = "買い" if str(direction).lower() == "buy" else "売り"
                    md = f"""\n| trade_mode | 銘柄 | 方向 | entry_price | SL | TP1 | TP2 | 判定 | ロット |\n|------------|------|------|-------------|----|-----|-----|------|-------|\n| {trade_mode} | {symbol} | {direction_jp} | {entry_price:.1f} | {sl_price:.1f} | {tp_price:.1f} | - | {signal} | {lots} |\n"""
                except Exception:
                    pass

                st.success("✅ 解析完了")
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("解析結果")
                    st.json(analysis)
                with col2:
                    st.subheader("IFD")
                    st.json(ifd)
                if md:
                    st.markdown("### IFD概要テーブル")
                    st.markdown(md)
            except Exception as e:
                st.error(f"❌ Direct解析エラー: {e}")
                st.caption("main.py 内の analyze_image_with_ai / manual30_ifd.generate_ifd を呼び出しています。")

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
