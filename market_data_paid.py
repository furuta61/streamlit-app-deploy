#!/usr/bin/env python3
"""
market_data_paid.py

Simple Twelve Data fetcher for JP225 / TOPIX (prototype).

Usage:
  - Set your Twelve Data API key in env: TWELVEDATA_API_KEY (or PAID_API_KEY)
  - Run: python3 market_data_paid.py JP225

Behavior:
  - Attempts a short list of candidate Twelve Data symbols for the logical keys
    'JP225' and 'TOPIX'. If a candidate returns a valid price, it is returned.
  - If none of the candidates return data, instructs user to set PAID_SYMBOL_JP225 / PAID_SYMBOL_TOPIX env var.

Note: This is intentionally conservative and aimed at local testing/prototyping.
For production, prefer official licensed JPX / QUICK feeds.
"""
import os
import sys
import time
import json
from typing import Optional, Tuple

try:
    import requests
except Exception:
    raise RuntimeError("'requests' is required. Please install via pip install requests")

API_BASE = "https://api.twelvedata.com"

# Candidate symbols to try (order matters). These are heuristic and may be adjusted.
# The module will also accept overrides via environment variables PAID_SYMBOL_JP225 / PAID_SYMBOL_TOPIX
CANDIDATE_SYMBOLS = {
    'JP225': [
        # Prefer JPX ETF tickers (Twelve Data often exposes ETF symbols without .T)
        '1321',  # Next Funds Nikkei 225 ETF (preferred)
        '1330',
        # yfinance-style tickers as fallback
        '1321.T',
        '1330.T',
        # index-style fallbacks (less reliable on Twelve Data)
        'NIKKEI:NI225',  # provider-like prefix
        '^N225',
        'NI225',
    ],
    'TOPIX': [
        'JPX:TOPX',
        '^TOPX',
        'TOPIX',
        '1306.T',  # ETF candidate
    ]
}


def _get_api_key() -> Optional[str]:
    return os.environ.get('TWELVEDATA_API_KEY') or os.environ.get('PAID_API_KEY')


def _call_price_endpoint(symbol: str, api_key: str, timeout: int = 8) -> Optional[dict]:
    """Call Twelve Data "price" endpoint and return JSON on success, else None."""
    url = f"{API_BASE}/price"
    try:
        r = requests.get(url, params={'symbol': symbol, 'apikey': api_key}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        # success usually contains {'symbol': 'xxx', 'price': '123.45', 'currency': 'JPY', ...}
        if isinstance(data, dict) and ('price' in data or 'value' in data):
            return data
        # sometimes API returns {'code':400, 'message':...}
        return None
    except Exception:
        return None


def _call_time_series(symbol: str, api_key: str, interval: str = '1min', outputsize: int = 1, timeout: int = 8) -> Optional[dict]:
    url = f"{API_BASE}/time_series"
    try:
        r = requests.get(url, params={'symbol': symbol, 'interval': interval, 'outputsize': outputsize, 'apikey': api_key}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        # expect {'status':'ok','meta':..., 'values':[{'datetime':'...', 'close':'...'}]}
        if isinstance(data, dict) and data.get('status') == 'ok' and 'values' in data and data['values']:
            return data
        return None
    except Exception:
        return None


def fetch_price(symbol_key: str) -> Tuple[Optional[float], Optional[str], Optional[dict]]:
    """
    Fetch latest price for logical symbol_key (e.g., 'JP225' or 'TOPIX').

    Returns: (price (float) or None, used_symbol (str) or None, raw_response(dict) or None)
    """
    symbol_key = symbol_key.upper()
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("Twelve Data API key not found. Set TWELVEDATA_API_KEY or PAID_API_KEY in your environment.")

    # 1) check for explicit override
    env_sym = os.environ.get(f'PAID_SYMBOL_{symbol_key}')
    candidates = []
    if env_sym:
        candidates.append(env_sym)

    # 2) append built-in candidates
    built = CANDIDATE_SYMBOLS.get(symbol_key)
    if built:
        candidates.extend(built)

    # 3) try each candidate: price endpoint first, fallback to time_series
    for cand in candidates:
        cand = cand.strip()
        if not cand:
            continue
        # try price endpoint
        data = _call_price_endpoint(cand, api_key)
        if data and ('price' in data or 'value' in data):
            try:
                price = float(data.get('price') or data.get('value'))
                return price, cand, data
            except Exception:
                # continue to try time_series
                pass
        # try time_series
        ts = _call_time_series(cand, api_key)
        if ts and 'values' in ts and ts['values']:
            try:
                latest = ts['values'][0]
                # prefer 'close' then 'price'
                val = latest.get('close') or latest.get('price') or latest.get('value')
                if val is None:
                    continue
                price = float(val)
                # include meta info
                meta = {'meta': ts.get('meta'), 'datetime': latest.get('datetime')}
                return price, cand, meta
            except Exception:
                continue

    # if we get here, no candidate worked
    return None, None, None


def _print_result(price, used_symbol, raw):
    if price is None:
        print("❌ 価格取得に失敗しました。候補が無効です。環境変数 PAID_SYMBOL_JP225 / PAID_SYMBOL_TOPIX を設定して正しい Twelve Data シンボルを指定してください。")
        return
    out = {
        'price': price,
        'symbol': used_symbol,
        'raw': raw
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def _cli(argv):
    if len(argv) < 1:
        print("Usage: market_data_paid.py SYMBOL_KEY [SYMBOL_KEY2 ...]\nExample: market_data_paid.py JP225 TOPIX")
        return 2
    for key in argv:
        try:
            price, used, raw = fetch_price(key)
            print(f"--- {key} ---")
            _print_result(price, used, raw)
        except Exception as e:
            print(f"ERROR fetching {key}: {e}")
    return 0


if __name__ == '__main__':
    sys.exit(_cli(sys.argv[1:]))
