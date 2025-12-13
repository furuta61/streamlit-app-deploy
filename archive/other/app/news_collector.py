import os, json, time, requests, sys
from datetime import datetime, timedelta
from dotenv import load_dotenv; load_dotenv()

from textblob import TextBlob

CACHE_DIR = "/tmp"
TTL = 3600  # 1時間キャッシュ
SHORT_TTL = 60  # 空結果の短めTTL（秒）

# シンボル毎のクエリ（日本語/英語を混在させて関連ニュースを拾いやすくする）
SYMBOL_NEWS_QUERY = {
    "JP225": "日経 OR 日本株 OR 日銀 OR 東京市場 OR Nikkei OR Japan OR Nikkei225",
    "US30": "Dow Jones OR 米株 OR 米国市場",
    "NQ100": "Nasdaq OR テック株 OR ハイテク企業",
    "XAUUSD": "Gold price OR 金相場 OR Bullion",
    "XAGUSD": "Silver price OR 銀相場",
    "NGAS": "Natural gas price OR エネルギー市場",
    "OIL": "原油 OR WTI OR crude oil",
    "GER40": "DAX OR ドイツ株 OR 欧州市場",
    "BTCUSD": "Bitcoin OR 仮想通貨 OR 暗号資産",
    "ETHUSD": "Ethereum OR ETHUSD OR 仮想通貨",
}


def analyze_sentiment(articles):
    scores = []
    for a in articles:
        try:
            text = a.get("title") or ""
            polarity = TextBlob(text).sentiment.polarity
            scores.append(polarity)
            a["sentiment"] = polarity
        except Exception:
            continue
    avg = sum(scores) / len(scores) if scores else 0.0
    print(f"🧠 Sentiment score (avg): {avg:.2f}")
    return avg


def _cache_path_for(symbol: str | None):
    if symbol:
        safe = symbol.upper().replace('/', '_')
        return os.path.join(CACHE_DIR, f"news_cache_{safe}.json")
    return os.path.join(CACHE_DIR, "news_cache_global.json")


def fetch_news(symbol: str | None = None, query="markets OR finance OR economy", country="jp", category=None, page_size=10):
    """symbol を渡せば銘柄固有クエリを優先して NewsAPI top-headlines を取得する。
    TTL キャッシュを /tmp/news_cache.json に置き、cache hit/miss を表示する。
    戻り値: 記事リスト（title/url/publishedAt）と sentiment_score を payload に入れて返す。
    """
    key = os.getenv("NEWS_API_KEY")
    if not key:
        print("⚠️ NEWS_API_KEY not set. Skipping news fetch.")
        return []

    # 銘柄が指定されていれば専用クエリを使う
    if symbol:
        q = SYMBOL_NEWS_QUERY.get(symbol.upper()) or query
    else:
        q = query

    cache_path = _cache_path_for(symbol)
    # キャッシュチェック（新フォーマット: dict with cached_at & ttl 推奨。既存のリスト形式にも対応）
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            # 既存のリスト形式だった場合は mtime で判定（後方互換）
            if isinstance(cached, list):
                mtime = os.path.getmtime(cache_path)
                if time.time() - mtime < TTL:
                    print("🗄️  Using cached news (legacy cache hit)")
                    return {"articles": cached, "sentiment_score": 0.0, "count": len(cached)}
            elif isinstance(cached, dict):
                cached_at = cached.get("cached_at")
                ttl_local = cached.get("ttl", TTL)
                if cached_at:
                    if time.time() - float(cached_at) < float(ttl_local):
                        print("🗄️  Using cached news (cache hit)")
                        return {"articles": cached.get("articles", []), "sentiment_score": cached.get("sentiment_score", 0.0), "count": cached.get("count", 0)}
                else:
                    # fallback: mtime-based
                    mtime = os.path.getmtime(cache_path)
                    if time.time() - mtime < TTL:
                        print("🗄️  Using cached news (cache hit, fallback)")
                        return {"articles": cached.get("articles", []), "sentiment_score": cached.get("sentiment_score", 0.0), "count": cached.get("count", 0)}
        except Exception:
            pass

    # APIリクエスト: everything を使う
    url = f"https://newsapi.org/v2/everything"

    # 英語と日本語を並列に叩き、結果をマージして重複を取り除く（並列マージ）
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_lang(lang: str):
        params = {"apiKey": key, "q": q, "pageSize": page_size, "language": lang}
        if category:
            params["category"] = category
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if "articles" not in data:
                return []
            items = [
                {"title": a.get("title"), "url": a.get("url"), "publishedAt": a.get("publishedAt")}
                for a in data.get("articles", [])
                if a.get("title")
            ]
            return items
        except Exception:
            return []

    langs = ["en", "ja"]
    results = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(_fetch_lang, l): l for l in langs}
        for fut in as_completed(futures):
            try:
                items = fut.result()
                if items:
                    results.extend(items)
            except Exception:
                continue

    # 重複除去: URL を優先キーに、なければ title をキーにする
    seen = set()
    merged = []
    for a in results:
        key_u = (a.get("url") or a.get("title") or "").strip()
        if not key_u:
            continue
        if key_u in seen:
            continue
        seen.add(key_u)
        merged.append(a)

    # 取得件数をページサイズでトリム
    articles = merged[:page_size]
    if not articles:
        print("⚠️ No news articles found for query (both langs)")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"articles": [], "sentiment_score": 0.0, "count": 0, "cached_at": time.time(), "ttl": SHORT_TTL}, f)
        except Exception:
            pass
        return {"articles": [], "sentiment_score": 0.0, "count": 0}

    # センチメント分析
    sentiment_score = analyze_sentiment(articles)
    # キャッシュ書き込み
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"articles": articles, "sentiment_score": sentiment_score, "count": len(articles), "cached_at": time.time(), "ttl": TTL}, f)
    except Exception:
        pass
    print(f"✅ fetched {len(articles)} news articles (cache miss, merged en+ja)")
    return {"articles": articles, "sentiment_score": sentiment_score, "count": len(articles), "language": "merged(en,ja)"}


if __name__ == "__main__":
    # allow symbol as argv
    sym = sys.argv[1] if len(sys.argv) > 1 else None
    result = fetch_news(symbol=sym)
    if not result:
        print("📈 No news fetched.")
    else:
        articles = result.get("articles") if isinstance(result, dict) else []
        print("📈 最新ニュース（上位10件）:")
        for i, n in enumerate(articles[:10], 1):
            print(f"[{i}] {n.get('title')}")
        print(f"✅ total {result.get('count', len(articles))} articles fetched")
