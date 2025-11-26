# sentiment_analyzer.py
from openai import OpenAI
import logging

client = OpenAI()
logger = logging.getLogger("sentiment")

def analyze_sentiment(text):
    """
    ニュース文の感情を分類し、ポジ／ネガ／中立の確率を返す
    """
    if not text.strip():
        return {"positive": 0, "neutral": 1, "negative": 0, "summary": ""}

    prompt = f"""
あなたは金融ニュースの感情分析AIです。
以下の文章の感情を数値化してください。
返答は次のJSON形式で出力してください。

{{"positive": 0.xx, "neutral": 0.xx, "negative": 0.xx, "summary": "日本語の要約"}}

{text}
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        content = res.choices[0].message.content
        if "{" in content:
            json_part = content[content.find("{"):]
            import json
            data = json.loads(json_part)
            return data
    except Exception as e:
        logger.warning(f"Sentiment error: {e}")

    return {"positive": 0.3, "neutral": 0.4, "negative": 0.3, "summary": text}
