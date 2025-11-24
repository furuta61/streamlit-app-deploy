# news_fetcher.py
import feedparser
import requests
from datetime import datetime, timedelta

# ---- RSSソース一覧 ----
RSS_FEEDS = {
    "fxstreet": "https://www.fxstreet.com/rss",
    "nikkei": "https://www.nikkei.com/rss/news",
    "marketscreener": "https://www.marketscreener.com/rss/lastnews/",
}

def fetch_latest_rss(limit=5):
    """RSSニュースを統合して返す"""
    items = []
    for name, url in RSS_FEEDS.items():
        feed = feedparser.parse(url)
        for entry in feed.entries[:limit]:
            items.append({
                "source": name,
                "title": entry.title,
                "summary": entry.get("summary", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
            })
    return items


# ---- X（旧Twitter）速報 ----
# APIが必要（無料制限あり）。ここでは「公式APIに接続する形」を提供。
# あなたのX APIキーを .env に入れれば動きます。

import os

X_BEARER = os.environ.get("X_BEARER_TOKEN")

def fetch_x_market_news(limit=5):
    """Xの市場速報（キーワードで抽出）"""
    if not X_BEARER:
        return []

    url = "https://api.twitter.com/2/tweets/search/recent"
    query = {
        "query": "(forex OR cfd OR index OR stocks OR market OR yen OR dax OR nikkei) lang:en",
        "max_results": limit
    }

    headers = {
        "Authorization": f"Bearer {X_BEARER}"
    }

    try:
        r = requests.get(url, params=query, headers=headers, timeout=6)
        data = r.json()
        tweets = data.get("data", [])
        return [{"source": "X", "text": t["text"]} for t in tweets]
    except Exception as e:
        return [{"source": "X", "error": str(e)}]
