# -*- coding: utf-8 -*-
"""
analyze_swing_multi_core.py
ニュース → 要約 → 感情分析（positive/negative）→ JSON返却

DawnAI / CFD3 DawnIFD のニュース統合モジュール
"""

import requests
import feedparser
from bs4 import BeautifulSoup
from openai import OpenAI
import os
import re
import html

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

# -------------------------------------------
# ★ ニュースソース（RSS）
# -------------------------------------------

NEWS_FEEDS = {
    "JP225": [
        "https://news.google.com/rss/search?q=日経平均+株&hl=ja&gl=JP&ceid=JP:ja",
        "https://news.yahoo.co.jp/rss/topics/business.xml"
    ],
    "NAS100": [
        "https://news.google.com/rss/search?q=NASDAQ+100+market&hl=en&gl=US&ceid=US:en"
    ],
    "GER40": [
        "https://news.google.com/rss/search?q=DAX+index+market&hl=en&gl=DE&ceid=DE:en"
    ],
    "XAUUSD": [
        "https://news.google.com/rss/search?q=gold+price+market&hl=en&gl=US&ceid=US:en"
    ]
}

# -------------------------------------------
# HTMLテキスト抽出
# -------------------------------------------

def clean_text(html_text):
    text = html.unescape(html_text)
    text = BeautifulSoup(text, "html.parser").get_text()
    text = re.sub(r"\s+", " ", text).strip()
    return text


# -------------------------------------------
# RSSから最新ニュースだけ抽出
# -------------------------------------------

def fetch_latest_news(symbol, limit=5):
    feeds = NEWS_FEEDS.get(symbol, [])
    collected = []

    for url in feeds:
        try:
            rss = feedparser.parse(url)
            for entry in rss.entries[:limit]:
                title = clean_text(entry.get("title", ""))
                summary = clean_text(entry.get("summary", ""))
                text = f"{title}。{summary}"
                if text:
                    collected.append(text)
        except Exception:
            continue

    return collected[:limit]


# -------------------------------------------
# GPTで要約 & 感情スコア生成
# -------------------------------------------

def analyze_news_sentiment(symbol):
    """
    戻り値:
    {
        "positive": 70,
        "negative": 40,
        "summary": "米テック株への買い圧力が強い"
    }
    """
    articles = fetch_latest_news(symbol)

    if not articles:
        return {
            "positive": 50,
            "negative": 50,
            "summary": ""
        }

    prompt = f"""
以下は {symbol} に関する最新ニュースです。
これらを 1 行で要約し、
さらにポジティブ / ネガティブ感情を 0〜100 で返してください。

ニュース:
{articles}

出力形式は JSON のみ:

{{
  "positive": 数値,
  "negative": 数値,
  "summary": "要約文"
}}
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        raw = res.choices[0].message.content
        data = eval(raw)  # GPTは JSONを返すため安全

        # バリデーション
        pos = float(data.get("positive", 50))
        neg = float(data.get("negative", 50))
        summary = data.get("summary", "")

        return {
            "positive": pos,
            "negative": neg,
            "summary": summary
        }

    except Exception as e:
        # ニュース取得失敗 → 中立として扱う（STOPを誘発しない）
        return {
            "positive": 50,
            "negative": 50,
            "summary": ""
        }


# -------------------------------------------
# テスト実行用
# -------------------------------------------

if __name__ == "__main__":
    for sym in ["JP225", "NAS100", "GER40", "XAUUSD"]:
        print("==", sym)
        print(analyze_news_sentiment(sym))
