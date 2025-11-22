#!/usr/bin/env python3
"""
market_data_ensemble.py

高精度モード用のアンサンブル取得器。複数ソース（Twelve Data の ETF、yfinance の ETF）を照合して
コンセンサス価格（中央値）と信頼度を返す。プロダクションではここを公式データ取得へ差し替えることが想定される。

関数:
  get_price(symbol_key: str) -> dict
    returns: { price: float|None, confidence: float(0-1), sources: [..] }

CLI も備える（デバッグ用）。
"""
import os
import time
import json
import statistics
from typing import List, Dict, Any, Callable

# defensive imports: allow module to be imported even if some optional deps are missing
try:
    import requests
except Exception:
    requests = None
try:
    import yfinance as yf
except Exception:
    yf = None
try:
    # optional EOD connector
    from market_data_eod import fetch_price as _fetch_eod_price
except Exception:
    _fetch_eod_price = None
try:
    # optional AlphaVantage connector
    from market_data_alpha import fetch_price as _fetch_alpha_price
except Exception:
    _fetch_alpha_price = None
try:
    # optional TradingView webhook source
    from market_data_tradingview import fetch_price as _fetch_tv_price
except Exception:
    _fetch_tv_price = None

TWELVEDATA_API_KEY = os.getenv('TWELVEDATA_API_KEY') or os.getenv('PAID_API_KEY')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

import re

# Configurable parameters
RETRY_COUNT = int(os.getenv('ENSEMBLE_RETRY_COUNT', '2'))
RETRY_BACKOFF = float(os.getenv('ENSEMBLE_RETRY_BACKOFF', '0.5'))
REQUEST_TIMEOUT = float(os.getenv('ENSEMBLE_REQUEST_TIMEOUT', '8.0'))

_SESSION = requests.Session() if requests is not None else None

def _log_error(msg: str):
    try:
        path = os.path.join(OUTPUT_DIR, 'ensemble_errors.log')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f"{time.time()} \t {msg}\n")
    except Exception:
        pass

def _retry_call(fn: Callable, *args, **kwargs):
    """Run fn with retries and exponential-ish backoff. Returns fn(...) result or raises last exception."""
    last_exc = None
    for attempt in range(RETRY_COUNT + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_BACKOFF * (1 + attempt))
            else:
                # final failure
                _log_error(f"retry_call failed for {fn.__name__}: {e}")
                raise
    # should not reach here
    if last_exc:
        raise last_exc

def _twelvedata_symbol_search(query: str) -> list:
    """Search Twelve Data symbols and return list of symbol strings (best-effort).
    Returns empty list on failure or if API key missing.
    """
    if not TWELVEDATA_API_KEY or requests is None:
        return []
    try:
        url = 'https://api.twelvedata.com/symbol_search'
        def _call():
            return _SESSION.get(url, params={'symbol': query, 'apikey': TWELVEDATA_API_KEY}, timeout=REQUEST_TIMEOUT)
        r = _retry_call(_call)
        r.raise_for_status()
        data = r.json()
        results = []
        for item in data.get('data', []):
            s = item.get('symbol') or item.get('symbol_name')
            if not s:
                continue
            # prefer numeric JPX ETF tickers like '1321', '1330'
            if re.match(r'^\d{3,4}$', s) or re.match(r'^\d{3,4}\.T$', s):
                results.append(s)
        # de-dup while preserving order
        seen = set(); out = []
        for s in results:
            if s not in seen:
                seen.add(s); out.append(s)
        return out
    except Exception as e:
        _log_error(f"twelvedata_symbol_search error: {e}")
        return []


def _fetch_twelvedata_price(symbol: str) -> float:
    """Twelve Data の簡易 price エンドポイントを叩く。symbol はプロバイダ表記（例: '1321'）。"""
    if not TWELVEDATA_API_KEY or requests is None:
        return None
    try:
        url = 'https://api.twelvedata.com/price'
        def _call():
            return _SESSION.get(url, params={'symbol': symbol, 'apikey': TWELVEDATA_API_KEY}, timeout=REQUEST_TIMEOUT)
        r = _retry_call(_call)
        r.raise_for_status()
        data = r.json()
        if 'price' in data:
            return float(data['price'])
    except Exception as e:
        _log_error(f"twelvedata price fetch error for {symbol}: {e}")
        return None
    return None


def _fetch_yfinance_price(symbol: str) -> float:
    """yfinance で最新の終値を取得。symbol 例: '1321.T'"""
    if yf is None:
        return None
    try:
        def _call():
            tk = yf.Ticker(symbol)
            return tk.history(period='1d', interval='1m')
        hist = _retry_call(_call)
        if hist is None or hist.empty:
            return None
        return float(hist['Close'].iloc[-1])
    except Exception as e:
        _log_error(f"yfinance fetch error for {symbol}: {e}")
        return None


def get_price(symbol_key: str) -> Dict[str, Any]:
    """指定した論理銘柄（例: 'JP225'）の高精度取得を試みる。

    戻り値の例:
      { 'price': 48000.0, 'confidence': 0.92, 'sources': [ {source, symbol, price}, ... ] }
    """
    # 現在は JP225 のみ専用候補を持つ。将来は設定ファイル化する。
    candidates = {
        'JP225': {
            'twelvedata': ['1321', '1330'],
            'yfinance': ['1321.T', '1330.T']
        }
    }

    if symbol_key not in candidates:
        return {'price': None, 'confidence': 0.0, 'sources': []}

    picks = candidates[symbol_key]
    sources = []

    # 1) Twelve Data（ETF表記）を順に試す
    td_candidates = list(picks.get('twelvedata', []))
    # 0) If requested, try official vendor feed first
    try:
        if os.getenv('USE_OFFICIAL', '1') == '1':
            try:
                from market_data_official import fetch_price as official_fetch
                off = official_fetch(symbol_key)
                if off and off.get('price') is not None:
                    # return early with official price
                    res = {'price': float(off['price']), 'confidence': 1.0, 'sources': [{'source': 'official', 'symbol': off.get('raw', {}).get('symbol', ''), 'price': float(off['price'])}], 'mad_rel': 0.0}
                    return res
            except Exception:
                # ignore and continue with ensemble
                pass
    except Exception:
        pass
    # if no candidates or not working, try symbol_search to discover ETFs
    if TWELVEDATA_API_KEY and requests is not None:
        try_queries = ['nikkei', 'n225', '1321']
        for q in try_queries:
            try:
                found = _twelvedata_symbol_search(q)
            except Exception:
                found = []
            if found:
                # prepend discovered symbols to candidate list
                for f in found:
                    if f not in td_candidates:
                        td_candidates.insert(0, f)
                break

    for s in td_candidates:
        try:
            p = _fetch_twelvedata_price(s)
        except Exception:
            p = None
        if p is not None:
            sources.append({'source': 'twelvedata', 'symbol': s, 'price': float(p)})
        time.sleep(0.05)

    # 2) yfinance を試す
    for s in picks.get('yfinance', []):
        try:
            p = _fetch_yfinance_price(s)
        except Exception:
            p = None
        if p is not None:
            sources.append({'source': 'yfinance', 'symbol': s, 'price': float(p)})
        time.sleep(0.05)

    # 2.b) TradingView webhook (optional) -- if present, prefer its near-real-time alert
    try:
        if _fetch_tv_price is not None:
            tv_res = _fetch_tv_price(symbol_key)
            if tv_res and tv_res.get('price') is not None:
                sources.append({'source': 'tradingview', 'symbol': tv_res.get('raw', {}).get('payload', {}).get('symbol', 'TV'), 'price': float(tv_res['price'])})
    except Exception as e:
        _log_error(f'tradingview fetch error: {e}')
    time.sleep(0.05)

    # 3) EOD (optional, low-cost provider) を試す
    try:
        if _fetch_eod_price is not None:
            eod_res = _fetch_eod_price(symbol_key)
            if eod_res and eod_res.get('price') is not None:
                sources.append({'source': 'eod', 'symbol': eod_res.get('raw', {}).get('symbol', 'OFFICIAL'), 'price': float(eod_res['price'])})
    except Exception as e:
        _log_error(f'eod fetch error: {e}')
    time.sleep(0.05)

    prices = [s['price'] for s in sources if s.get('price') is not None]
    if not prices:
        return {'price': None, 'confidence': 0.0, 'sources': sources}
    # --------- Improved aggregation: weighted median + trimmed mean fallback ---------
    # Assign source weights (can be tuned via env vars)
    weights_map = {
        'twelvedata': float(os.getenv('WEIGHT_TWELVE', '2.0')),
        'eod': float(os.getenv('WEIGHT_EOD', '1.5')),
        'alpha': float(os.getenv('WEIGHT_ALPHA', '1.2')),
        'yfinance': float(os.getenv('WEIGHT_YF', '1.0')),
        'official': float(os.getenv('WEIGHT_OFFICIAL', '3.0'))
    }

    # Build list of (price, weight) aligned with sources order
    price_weight_pairs = []
    for s in sources:
        src = s.get('source')
        p = s.get('price')
        w = weights_map.get(src, 1.0)
        try:
            price_weight_pairs.append((float(p), float(w)))
        except Exception:
            continue

    def weighted_median(pairs):
        # pairs: list of (price, weight)
        if not pairs:
            return None
        pairs_sorted = sorted(pairs, key=lambda x: x[0])
        total_w = sum(w for _, w in pairs_sorted)
        if total_w == 0:
            return pairs_sorted[len(pairs_sorted)//2][0]
        cum = 0.0
        for price, w in pairs_sorted:
            cum += w
            if cum >= total_w / 2.0:
                return price
        return pairs_sorted[-1][0]

    def mad_rel_from(center, vals):
        devs = [abs(v - center) for v in vals]
        mad = statistics.mean(devs) if devs else 0.0
        return (mad / center) if center != 0 else 0.0

    # compute weighted median
    wm = weighted_median(price_weight_pairs)

    # trimmed mean: remove values beyond 2*MAD from median
    raw_prices = [p for p in prices]
    mad_rel_val = mad_rel_from(wm, raw_prices) if wm is not None else 0.0
    # determine threshold in absolute value
    try:
        mad_abs = statistics.mean([abs(p - wm) for p in raw_prices])
    except Exception:
        mad_abs = 0.0
    trim_thresh = 2.0 * mad_abs
    trimmed = [p for p in raw_prices if abs(p - wm) <= trim_thresh]
    if trimmed:
        trimmed_mean = float(sum(trimmed) / len(trimmed))
    else:
        trimmed_mean = float(wm)

    # final price decision: prefer weighted median; if high dispersion use trimmed mean
    dispersion = mad_rel_val
    if dispersion > float(os.getenv('ENSEMBLE_DISPERSION_SWITCH', '0.01')):
        chosen_price = float(trimmed_mean)
    else:
        chosen_price = float(wm)

    # Confidence scoring: inverse of relative MAD, scaled by number of sources and max weight
    try:
        src_count = max(1, len(price_weight_pairs))
        max_w = max(w for _, w in price_weight_pairs)
        confidence = max(0.0, min(1.0, 1.0 / (1.0 + mad_rel_val * 100.0) * (src_count / (1.0 + max_w/2.0))))
    except Exception:
        confidence = 0.0

    res = {
        'price': float(chosen_price),
        'confidence': float(confidence),
        'sources': sources,
        'mad_rel': float(mad_rel_val)
    }

    # Logging: append a JSON line with timestamp
    try:
        import json
        out_path = os.path.join(OUTPUT_DIR, 'ensemble_log.jsonl')
        entry = {
            'ts': time.time(),
            'symbol_key': symbol_key,
            'price': res['price'],
            'confidence': res['confidence'],
            'mad_rel': res['mad_rel'],
            'sources': res['sources']
        }
        with open(out_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass

    # Alerting: if confidence below threshold, send alert (best-effort)
    try:
        conf_threshold = float(os.getenv('ENSEMBLE_CONF_THRESHOLD', '0.5'))
        if float(confidence) < conf_threshold and os.getenv('ENSEMBLE_ALERT_ENABLED', '1') == '1':
            try:
                # lazy import to avoid circular deps
                from alerts import send_alert
                subj = f"[CFD3] Low ensemble confidence for {symbol_key}: {confidence:.2f}"
                body = f"ensemble_price={res['price']} confidence={res['confidence']:.3f} mad_rel={res['mad_rel']:.6f}\nSources: {res['sources']}"
                recipient = os.getenv('RECIPIENT') or os.getenv('EMAIL_USER')
                if recipient:
                    send_alert(recipient, subj, body, attachments=[])
            except Exception:
                pass
    except Exception:
        pass

    return res


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: market_data_ensemble.py SYMBOL_KEY (e.g. JP225)')
        sys.exit(2)

    key = sys.argv[1]
    res = get_price(key)
    print('Result:')
    print(json.dumps(res, indent=2, ensure_ascii=False))
