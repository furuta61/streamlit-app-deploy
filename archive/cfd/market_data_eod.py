#!/usr/bin/env python3
"""
market_data_eod.py

EOD Historical Data の簡易コネクタ（最小実装）。

関数:
  fetch_price(symbol_key: str) -> dict | None
    returns: { 'price': float, 'raw': {...} } on success, or None on failure / no-key.

注意: EOD の API キーが環境変数 `EOD_API_KEY` に設定されている必要があります。
このファイルは defensive に実装しており、キーが無い場合は単に None を返します。
"""
import os
import time
import json
try:
    import requests
except Exception:
    requests = None

EOD_API_KEY = os.getenv('EOD_API_KEY')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output') if '__file__' in globals() else 'output'
os.makedirs(OUTPUT_DIR, exist_ok=True)
EOD_STATUS_PATH = os.path.join(OUTPUT_DIR, 'eod_status.json')

def _log(msg: str):
    try:
        path = os.path.join(OUTPUT_DIR, 'market_data_eod.log')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f"{time.time()}\t{msg}\n")
    except Exception:
        pass


def _try_parse_price(data):
    """Try to extract a price from a JSON-decoded response (best-effort)."""
    if data is None:
        return None
    # direct keys
    for key in ('price', 'last', 'close', 'p', 'adjusted_close'):
        if key in data and data.get(key) is not None:
            try:
                return float(data.get(key))
            except Exception:
                continue
    # nested under 'data' or 'quote'
    for container in ('data', 'quote', 'Realtime', 'Last'):
        if isinstance(data.get(container), dict):
            for key in ('price', 'last', 'close', 'p'):
                if key in data[container] and data[container].get(key) is not None:
                    try:
                        return float(data[container].get(key))
                    except Exception:
                        continue
    return None


def fetch_price(symbol_key: str):
    """Fetch a latest price for logical symbol_key (e.g. 'JP225').

    Returns a dict {'price': float, 'raw': {...}} or None.
    The implementation is defensive and will try several URL patterns commonly used by EOD-like APIs,
    logging the raw responses to aid debugging.
    """
    # short-circuit if no requests lib or no API key
    if requests is None or not EOD_API_KEY:
        _log('requests missing or EOD_API_KEY not set')
        return None

    # If we've recently seen unauthorized errors, back off to avoid hammering the API.
    try:
        if os.path.exists(EOD_STATUS_PATH):
            with open(EOD_STATUS_PATH, 'r', encoding='utf-8') as fh:
                st = json.load(fh)
            until = float(st.get('unavailable_until', 0))
            if time.time() < until:
                _log(f'EOD marked unavailable until {until}; skipping attempts')
                return None
    except Exception:
        # ignore status-file issues
        pass

    # Map logical key to a provider symbol
    symbol_map = {
        'JP225': os.getenv('OFFICIAL_SYMBOL_JP225', 'N225'),
    }
    provider_symbol = symbol_map.get(symbol_key)
    if not provider_symbol:
        _log(f'no provider symbol mapping for {symbol_key}')
        return None

    # try multiple patterns / endpoints to increase chance of success
    base_rt = 'https://eodhistoricaldata.com/api/real-time/'
    base_eod = 'https://eodhistoricaldata.com/api/eod/'
    candidates = []
    # prefer raw provider symbol
    candidates.append(f"{base_rt}{provider_symbol}")
    candidates.append(f"{base_rt}{provider_symbol}.L")
    candidates.append(f"{base_rt}{provider_symbol}.T")
    candidates.append(f"{base_eod}{provider_symbol}")
    candidates.append(f"{base_eod}{provider_symbol}.L")
    candidates.append(f"{base_eod}{provider_symbol}.T")

    params = {'api_token': EOD_API_KEY, 'fmt': 'json'}
    timeout = float(os.getenv('EOD_REQUEST_TIMEOUT', '8.0'))

    # auth modes to try: query param, Authorization: Bearer, Authorization: Token
    auth_modes = ['param', 'bearer', 'token']

    headers_base = {
        'User-Agent': os.getenv('EOD_USER_AGENT', 'CFD3_AutoSystem/1.0 (+https://example.local)') ,
        'Accept': 'application/json',
    }

    saw_unauth = False
    for url in candidates:
        for mode in auth_modes:
            try:
                _log(f'Trying EOD URL: {url} (auth_mode={mode})')
                headers = dict(headers_base)
                req_params = None
                if mode == 'param':
                    req_params = params
                    r = requests.get(url, params=req_params, timeout=timeout, headers=headers)
                else:
                    # supply token in Authorization header
                    token = EOD_API_KEY
                    if mode == 'bearer':
                        headers['Authorization'] = f'Bearer {token}'
                    else:
                        # some APIs accept 'Token <token>' instead
                        headers['Authorization'] = f'Token {token}'
                    r = requests.get(url, timeout=timeout, headers=headers)

                _log(f'EOD HTTP {r.status_code} for {url} (auth_mode={mode})')
                text = r.text[:4000] if r.text else ''
                _log(f'Raw response (truncated): {text}')
                try:
                    data = r.json()
                except Exception:
                    data = None

                # If we get a clear 401/Unauthenticated, continue to next auth mode quickly
                if r.status_code in (401, 403):
                    _log(f'EOD unauthorized ({r.status_code}) for {url} with mode={mode}')
                    saw_unauth = True
                    continue

                price = _try_parse_price(data)
                if price is not None:
                    return {'price': float(price), 'raw': data or text}
            except Exception as e:
                _log(f'EOD fetch error for {provider_symbol} via {url} (mode={mode}): {e}')
                continue

    # If we observed authorization errors across attempts, write a short backoff marker
    try:
        if saw_unauth:
            backoff_hours = float(os.getenv('EOD_BACKOFF_HOURS', '6'))
            until = time.time() + backoff_hours * 3600.0
            with open(EOD_STATUS_PATH, 'w', encoding='utf-8') as fh:
                json.dump({'unavailable_until': until, 'ts': time.time()}, fh)
            _log(f'Wrote EOD unavailable marker until {until} (backoff_hours={backoff_hours})')
    except Exception as e:
        _log(f'Failed writing EOD status file: {e}')

    _log(f'All EOD attempts failed for {provider_symbol}')
    return None


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: market_data_eod.py SYMBOL_KEY')
        sys.exit(2)
    res = fetch_price(sys.argv[1])
    print(json.dumps(res, ensure_ascii=False, indent=2))
