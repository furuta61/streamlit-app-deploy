#!/usr/bin/env python3
"""
market_data_alpha.py

AlphaVantage の簡易コネクタ（防御的実装）。
関数:
  fetch_price(symbol_key: str) -> dict | None
    returns: { 'price': float, 'raw': {...} } on success, or None on failure / no-key.

環境変数: ALPHAVANTAGE_API_KEY
"""
import os
import time
try:
    import requests
except Exception:
    requests = None

API_KEY = os.getenv('ALPHAVANTAGE_API_KEY')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output') if '__file__' in globals() else 'output'
try:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
except Exception:
    pass


def _log(msg: str):
    try:
        path = os.path.join(OUTPUT_DIR, 'market_data_alpha.log')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f"{time.time()}\t{msg}\n")
    except Exception:
        pass


def _try_parse_price(data):
    if data is None:
        return None
    # common AlphaVantage fields
    # TIME_SERIES_DAILY returns 'Time Series (Daily)' with dates-> {"4. close": "..."}
    if isinstance(data, dict):
        for key in data:
            if key.startswith('Time Series') and isinstance(data[key], dict):
                # take latest date
                dates = sorted(data[key].keys())
                if not dates:
                    continue
                latest = data[key][dates[-1]]
                for field in ('4. close', 'close', 'price'):
                    if field in latest:
                        try:
                            return float(latest[field])
                        except Exception:
                            continue
        # some realtime endpoints return 'price' or 'close' top-level
        for f in ('price','close'):
            if f in data:
                try:
                    return float(data[f])
                except Exception:
                    pass
    return None


def fetch_price(symbol_key: str):
    """Attempt to fetch a recent price for logical symbol_key.
    Maps JP225 -> tries ETF tickers (1321.T,1330.T) or OFFICIAL_SYMBOL_JP225.
    """
    if requests is None or not API_KEY:
        _log('requests missing or ALPHAVANTAGE_API_KEY not set')
        return None

    # map logical symbol
    candidates = []
    # try explicit env override first
    off = os.getenv('OFFICIAL_SYMBOL_JP225')
    if off:
        candidates.append(off)
    # common ETF tickers
    candidates.extend(['1321.T','1330.T','^N225','N225'])

    base = 'https://www.alphavantage.co/query'
    for sym in candidates:
        try:
            # Prefer TIME_SERIES_DAILY for ETFs/indices
            params = {'function':'TIME_SERIES_DAILY','symbol':sym,'apikey':API_KEY,'outputsize':'compact'}
            r = requests.get(base, params=params, timeout=float(os.getenv('ALPHA_REQUEST_TIMEOUT','8.0')))
            _log(f'Alpha HTTP {r.status_code} for {sym}')
            try:
                data = r.json()
            except Exception:
                data = None
            price = _try_parse_price(data)
            if price is not None:
                return {'price': float(price), 'raw': data}
        except Exception as e:
            _log(f'Alpha fetch error for {sym}: {e}')
            continue
    _log('Alpha: all attempts failed')
    return None


if __name__ == '__main__':
    import sys, json
    if len(sys.argv) < 2:
        print('Usage: market_data_alpha.py SYMBOL_KEY')
        sys.exit(2)
    res = fetch_price(sys.argv[1])
    print(json.dumps(res, ensure_ascii=False, indent=2))
