# gpt_vision_reader.py
# GPT Vision を使って iPhoneスクショから CFD4銘柄の価格を抽出

import base64
from openai import OpenAI

client = OpenAI()   # APIキーは環境変数 OPENAI_API_KEY を使用

PROMPT = """
あなたはCFD価格抽出AIです。
画像から次の4つの銘柄の「一番大きく表示されている価格だけ」を読み取り、
JSONのみを返してください。

- 日本225 → JP225
- 米国NQ100ミニ → NAS100
- ドイツ40 → GER40
- 金スポット → XAUUSD

注意:
- 小さく表示されている詳細価格は無視する
- BID/ASK の区別が不要。とにかく「巨大フォントの価格」を返す
- 数値のみ返す（カンマ禁止、通貨記号禁止）
- JSON以外の文字列を絶対に返さない
出力例:
{
  "JP225": 48466.0,
  "NAS100": 24553.3,
  "GER40": 23208.0,
  "XAUUSD": 4089.96
}
"""

def gpt_extract_prices(image_path: str) -> dict:
    """GPT Vision を使ってスクショから4銘柄の価格を抽出する"""

    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except Exception as e:
        return {"error": f"画像を開けません: {str(e)}"}

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",   # Vision対応モデル
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"}
                        }
                    ]
                }
            ]
        )

        content = res.choices[0].message.content.strip()
        
        # コードブロックを除去 (```json ... ```)
        if content.startswith("```"):
            lines = content.split("\n")
            # 最初と最後の行を除去
            content = "\n".join(lines[1:-1])
            # 再度トリム
            content = content.strip()

        # JSONとして読み取る
        import json
        return json.loads(content)

    except Exception as e:
        return {"error": f"GPT Vision OCR に失敗しました: {str(e)}"}
