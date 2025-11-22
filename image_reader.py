import cv2
import numpy as np
import pytesseract
import re
from typing import Dict, Any, Union, BinaryIO


# iPhone ウォッチリスト画面（大きな価格表示）専用
# 各銘柄の価格が非常に大きく表示される画面
SYMBOL_ORDER = ["JP225", "NAS100", "GER40", "XAUUSD"]

# OCR設定: 数字と小数点のみ
TESS_CONFIG = "--psm 7 -c tessedit_char_whitelist=0123456789."


def _extract_from_iphone_watchlist(img: np.ndarray) -> Dict[str, Any]:
    """
    iPhone 16 Pro Max のウォッチリスト縦スクショから
    4銘柄の現在値を抽出する。
    戻り値:
      {"JP225": {"bid": 48466.0, "ask": 48466.0}, ...}
    """

    h, w = img.shape[:2]

    # 画面の上部・下部にあるステータスバー/タブバーを除いた有効エリアを
    # 「縦に4分割して各行を読む」という考え方
    header_ratio = 0.12   # 上の時計・検索バーなど
    bottom_ratio = 0.10   # 下のタブバー

    usable_h = h * (1.0 - header_ratio - bottom_ratio)
    row_h = usable_h / 4.0
    y_start0 = int(h * header_ratio)

    # 横方向: 価格が出ているのは右寄りの大きな数字なので、
    # 画面幅の 0.32〜0.95 くらいを読む
    x1 = int(w * 0.32)
    x2 = int(w * 0.95)

    results: Dict[str, Any] = {}

    for idx, symbol in enumerate(SYMBOL_ORDER):
        # 各銘柄の行（縦方向）
        y1_full = int(y_start0 + idx * row_h)
        y2_full = int(y1_full + row_h)

        # ★ 重要: 価格の大きな白文字だけを狙う（上から10%〜35%の範囲）
        y1 = int(y1_full + row_h * 0.10)
        y2 = int(y1_full + row_h * 0.35)

        roi = img[y1:y2, x1:x2]

        # --- 前処理: 3倍拡大してOCR精度向上 ---
        roi_large = cv2.resize(roi, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(roi_large, cv2.COLOR_BGR2GRAY)
        
        # Otsu二値化
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # --- 数字だけ OCR (PSM 7: 単一行) ---
        text = pytesseract.image_to_string(
            th,
            lang="eng",
            config="--psm 7 -c tessedit_char_whitelist=0123456789.",
        )

        # 価格パターンを抽出: 5桁以上の数字を優先
        # まず5桁以上の数字を探す
        nums_long = re.findall(r"\d{5,6}(?:\.\d{1,2})?", text)
        
        if nums_long:
            best = nums_long[0]
        else:
            # 4桁の数字も許容（XAUUSD等）
            nums = re.findall(r"\d{4,6}(?:\.\d{1,2})?", text)
            if not nums:
                continue
            best = nums[0]
        try:
            price = float(best)
        except ValueError:
            continue

        results[symbol] = {"bid": price, "ask": price}

    if not results:
        return {"error": "価格を抽出できませんでした"}

    return results


def extract_prices_from_image(image_bytes: Union[bytes, BinaryIO]) -> Dict[str, Any]:
    """
    メインエントリ:
      - image_bytes: bytes か、.read() を持つファイルライクオブジェクト
    """

    if hasattr(image_bytes, "read"):
        data = image_bytes.read()
    else:
        data = image_bytes

    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if img is None:
        return {"error": "画像を読み込めませんでした"}

    h, w = img.shape[:2]
    aspect = h / max(w, 1)

    # 縦長（iPhone縦スクショ）だけ対応
    if aspect > 1.8:
        return _extract_from_iphone_watchlist(img)

    return {"error": "現在は iPhone 縦スクショのみ対応です"}

