from __future__ import annotations
import os
import sys
import time
from typing import Dict, Any
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime

# --- 設定項目（環境変数）---
GMO_LOGIN_ID = os.getenv("GMO_LOGIN_ID")
GMO_PASSWORD = os.getenv("GMO_PASSWORD")
# ▼追加: 自動発注有効フラグ (1 にすると本番実行)
GMO_AUTOMATION_ENABLED = os.getenv("GMO_AUTOMATION_ENABLED")

# CFD3システム上のシンボル名と、GMOでの実際の銘柄名の対応表
# 実運用時はご自身のGMO画面表示名に合わせて調整してください
GMO_SYMBOL_MAP = {
    "JP225": "日本225",
    "NQ100": "米国NQ100",
    "XAUUSD": "金スポット",
    "XAGUSD": "銀スポット",
        "NGAS": "天然ガス",
        "GER40": "ドイツ40",
        # 追加: 銅は GMO 上で先物として扱われるため画面表示に合わせて "銅先物" を登録
        "COPPER": "銅先物",
}

# Per-broker scale factors to convert internal instrument prices to broker-displayed units.
# Set environment variables like BROKER_SCALE_US30=1.376623478 to correct scale when needed.
BROKER_PRICE_SCALE = {
    'US30': float(os.getenv('BROKER_SCALE_US30', '1.0')),
}


def execute_gmo_order(ifd_order: Dict[str, Any]):
    """Selenium を使って GMO クリック証券のブラウザ画面から IFD 注文を発注する（最小実装）。

    注意:
    - 実際のページ要素 (ID/CSS) は GMO の画面によって異なり、要調整です。
    - 本スクリプトは `GMO_LOGIN_ID` と `GMO_PASSWORD` を環境変数から読み込みます。
    - 自動発注はリスクを伴います。まずは headless をオフにして手動確認でテストしてください。
    """
    # dry-run チェック: 環境変数 GMO_AUTOMATION_ENABLED が "1" でない限り実行しない
    if GMO_AUTOMATION_ENABLED != "1":
        print("--- 💧 Dry Run Mode ---")
        print("自動発注は無効です。以下の注文が実行される予定でした：")
        print(f"  銘柄: {ifd_order.get('symbol')}")
        print(f"  Entry: {ifd_order.get('entry_price')}")
        print(f"  TP: {ifd_order.get('take_profit')}")
        print(f"  SL: {ifd_order.get('stop_loss')}")
        print("----------------------")
        return

    if not all([GMO_LOGIN_ID, GMO_PASSWORD]):
        print("❌ GMO のログイン情報が環境変数に設定されていません。自動発注をスキップします。", file=sys.stderr)
        return

    options = webdriver.ChromeOptions()
    # 実運用時は headless に切り替えることも可能ですが、初期は可視モードでデバッグしてください
    # options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    wait = WebDriverWait(driver, 20)

    try:
        # 1. ログインページへ
        print("... GMO にログイン中")
        driver.get("https://www.click-sec.com/login/")

        # 以下のセレクタは仮定です。実際の要素はブラウザで確認して合わせてください。
        wait.until(EC.presence_of_element_located((By.ID, "login_id"))).send_keys(GMO_LOGIN_ID)
        driver.find_element(By.ID, "login_password").send_keys(GMO_PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()

        # 2. CFD 取引画面へ移動
        print("... CFD 取引画面へ遷移")
        try:
            wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "CFD"))).click()
        except Exception:
            # サイト構成によってはメニュー名が異なることがある
            pass

        # 新しいウィンドウが開く場合は切り替える
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])

        symbol = ifd_order.get("symbol")
        gmo_symbol = GMO_SYMBOL_MAP.get(symbol)
        if not gmo_symbol:
            raise ValueError(f"銘柄 {symbol} が GMO_SYMBOL_MAP に見つかりません。マップを確認してください。")

        print(f"... 銘柄 {gmo_symbol} の IFD 注文を準備")

        # --- 銘柄選択（仮） ---
        wait.until(EC.element_to_be_clickable((By.ID, "symbol_search_input"))).send_keys(gmo_symbol)
        driver.find_element(By.ID, "symbol_select_button").click()

        # IFD タブ選択（仮）
        wait.until(EC.element_to_be_clickable((By.ID, "order_type_ifd_tab"))).click()

        # 価格入力（仮）
        entry = ifd_order.get("entry_price")
        tp = ifd_order.get("take_profit")
        sl = ifd_order.get("stop_loss")

        # apply broker-specific scaling if configured (fixes scale mismatches like US30)
        scale = BROKER_PRICE_SCALE.get(symbol, 1.0) or 1.0
        def fmt_price_for_broker(v):
            if v is None or v == '':
                return ''
            try:
                fv = float(v) * float(scale)
            except Exception:
                fv = float(v)
            # format: if large int-like, send as int; else 4 decimals trimmed
            if abs(fv) >= 1000 and abs(fv - round(fv)) < 1e-6:
                return str(int(round(fv)))
            return f"{fv:.4f}".rstrip('0').rstrip('.')

        entry_s = fmt_price_for_broker(entry)
        tp_s = fmt_price_for_broker(tp)
        sl_s = fmt_price_for_broker(sl)

        wait.until(EC.presence_of_element_located((By.ID, "ifd_entry_price"))).send_keys(entry_s)
        driver.find_element(By.ID, "ifd_take_profit_price").send_keys(tp_s)
        driver.find_element(By.ID, "ifd_stop_loss_price").send_keys(sl_s)

        # 注文確認 → 実行
        print("... 注文内容を確認し、発注を実行")
        driver.find_element(By.ID, "confirm_order_button").click()
        wait.until(EC.element_to_be_clickable((By.ID, "execute_order_button"))).click()

        # スクリーンショットを保存
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = os.path.join(os.getcwd(), "output", f"gmo_order_{symbol}_{timestamp}.png")
        driver.save_screenshot(screenshot_path)
        print(f"✅ 注文完了（スクリーンショット保存）: {screenshot_path}")

    except Exception as e:
        print(f"❌ GMO 自動発注でエラー: {e}", file=sys.stderr)
        try:
            errshot = os.path.join(os.getcwd(), "output", f"gmo_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            driver.save_screenshot(errshot)
            print(f"(エラー時スクショ) {errshot}")
        except Exception:
            pass
    finally:
        print("... ブラウザを終了します")
        time.sleep(2)
        try:
            driver.quit()
        except Exception:
            pass
