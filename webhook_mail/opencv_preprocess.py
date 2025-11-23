import cv2
import numpy as np

def preprocess_image(image_bytes: bytes) -> bytes:
    """OpenCVで画像のコントラスト強化・ノイズ除去を行い二値化したバイト列を返す。失敗時は入力をそのまま返す。"""
    try:
        npimg = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        equalized = cv2.equalizeHist(blur)
        _, binary = cv2.threshold(equalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, buf = cv2.imencode('.png', binary)
        return buf.tobytes()
    except Exception:
        return image_bytes
