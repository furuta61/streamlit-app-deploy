# -*- coding: utf-8 -*-
"""
scripts/show_ifd_table.py

現在価格（環境変数または yfinance）から IFD 値を計算し、
レーティング降順（おすすめ順）でGMO に転記しやすい Markdown テーブルとして出力します。
売買方向（買い/売り）を明記します。

優先順位:
- 環境変数 PRICE_<SYMBOL>（例: PRICE_JP225=50161.5）
- yfinance（`app/price_fetcher.fetch_price`）

任意でニュースを統合（NEWS_API_KEY がセット、または IFD_INCLUDE_NEWS=1 の場合）
- `app/news_collector.fetch_news(symbol)` を呼んで news_count / sentiment_score を meta に付与

使い方:
  python3 -c "from mygpt_strategy import generate_ifd; exec(open('scripts/show_ifd_table.py').read())"
"""
import os
from mygpt_strategy import generate_ifd, analyze_signal

# 価格取得
try:
    from app.price_fetcher import fetch_price as _fetch_price
except Exception:
    _fetch_price = None

# ニュース取得（任意）
try:
    from app.news_collector import fetch_news as _fetch_news
except Exception:
    _fetch_news = None

SYMBOLS = ["JP225", "NQ100", "GER40", "XAUUSD", "XAGUSD", "NGAS"]

# 環境変数から価格を読む
def _env_price(symbol: str):
    key = f"PRICE_{symbol}"
    v = os.getenv(key)
    if not v:
        return None
    try:
        return float(v)
    except Exception:
        return None

# ニュースメタ（任意）
USE_NEWS = os.getenv("IFD_INCLUDE_NEWS") in ("1", "true", "True") or bool(os.getenv("NEWS_API_KEY"))

def _get_meta_with_news(symbol: str):
    if not USE_NEWS or not _fetch_news:
        return {}
    try:
        r = _fetch_news(symbol)
        if isinstance(r, dict):
            arts = r.get("articles", []) or []
            return {
                "news_refs": [a.get("title") for a in arts][:3],
                "news_count": len(arts),
                "sentiment_score": float(r.get("sentiment_score", 0.0) or 0.0),
            }
        elif isinstance(r, list):
            return {
                "news_refs": [str(a) for a in r][:3],
                "news_count": len(r),
                "sentiment_score": 0.0,
            }
    except Exception:
        pass
    return {}

# 価格とスクリーナを決定
prices = {}
screeners = {}
for s in SYMBOLS:
    p = _env_price(s)
    if p is None and _fetch_price:
        try:
            fp = _fetch_price(s)
            p = fp.get("price")
        except Exception:
            p = None
    prices[s] = p

# analyze_signal を呼んで rating と side を決定
analyses = {}
for s in SYMBOLS:
    price = prices.get(s)
    if price is None:
        analyses[s] = None
        continue
    # ダミーペイロード（必要に応じて screener を渡す）
    # デフォルトシグナルは STRONG_GO（CSVシステムの高評価を想定）
    payload = {"signal": "STRONG_GO", "price": price}
    # ニュース
    news_meta = _get_meta_with_news(s)
    if news_meta:
        payload.update(news_meta)
    try:
        analysis = analyze_signal(s, payload)
        analyses[s] = analysis
    except Exception:
        analyses[s] = None

# レーティングでソート（降順）
sorted_symbols = sorted(SYMBOLS, key=lambda s: analyses.get(s, {}).get("rating", 0.0) if analyses.get(s) else 0.0, reverse=True)

# 出力ヘッダ
print("## 6銘柄 IFD注文（おすすめ順・売買方向明記）\n")
print("| 銘柄 | 売買 | 判定 | rating | entry_price | TP1 | SL | order_type | 推奨度 | ロット | news_count | sentiment_score |")
print("|------|------|------|--------|-------------|-----|-----|------------|--------|--------|------------|-----------------|")

for s in sorted_symbols:
    price = prices.get(s)
    ana = analyses.get(s)
    if price is None or ana is None:
        # 価格が取れない場合はスキップ行
        print(f"| {s} | - | - | - | - | - | - | - | - | - | - | - |")
        continue

    decision = ana.get("decision", "GO")
    side = ana.get("side", "BUY")
    rating = ana.get("rating", 0.0)

    meta = {
        "rating": rating,
        "side": side,
        "news_refs": ana.get("news_refs", []),
        "news_count": ana.get("news_count", 0) if ana.get("news_count") is not None else 0,
        "sentiment_score": ana.get("sentiment_score", 0.0),
    }

    ifd = generate_ifd(s, price, decision, meta=meta, side=side)
    e = ifd['entry_price']
    tp = ifd['take_profit']
    sl = ifd['stop_loss']

    # 表示フォーマットと注文種別
    if s in ['JP225','NQ100','GER40']:
        entry = f"{int(e):,}"
        tp1 = f"{int(tp):,}"
        slv = f"{int(sl):,}"
        order_type = "指値"
    elif s == 'NGAS':
        entry = f"{e:.3f}"
        tp1 = f"{tp:.3f}"
        slv = f"{sl:.3f}"
        order_type = "成行"
    else:
        entry = f"{e:.2f}"
        tp1 = f"{tp:.2f}"
        slv = f"{sl:.2f}"
        order_type = "指値"

    news_count = ifd.get('news_count', 0)
    sentiment = ifd.get('sentiment_score', 0.0)

    side_jp = "買い" if side == "BUY" else "売り"
    rating_str = f"{rating:.2f}"

    # 推奨度（★の数）- GO判定以上は最低★★★
    if decision in ["STRONG_GO", "GO"]:
        # GO以上の判定は最低★★★を保証
        if rating >= 6.0:
            stars = "★★★★★"
        elif rating >= 5.0:
            stars = "★★★★"
        else:
            stars = "★★★"  # GO判定なら rating < 5.0 でも★★★
    else:
        # WAIT判定は通常通り
        if rating >= 4.0:
            stars = "★★★"
        elif rating >= 3.0:
            stars = "★★"
        else:
            stars = "★"

    print(f"| {s} | {side_jp} | {decision} | {rating_str} | {entry} | {tp1} | {slv} | {order_type} | {stars} | 2–3 | {news_count if news_count is not None else '-'} | {f'{sentiment:.2f}' if isinstance(sentiment, (int,float)) else '-'} |")

