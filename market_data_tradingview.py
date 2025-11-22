#!/usr/bin/env python3
"""
market_data_tradingview.py

Helper to read the latest TradingView webhook entry from `output/tradingview.jsonl`.
This is intentionally simple: TradingView alerts are appended by the webhook listener,
and this module exposes `fetch_price(symbol_key)` which returns {'price': float, 'raw': {...}} or None.
"""
import os
import json
import time
from typing import Optional, Dict, Any

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
TV_PATH = os.path.join(OUTPUT_DIR, 'tradingview.jsonl')

# Optional tradingview_ta integration (screener data). Import lazily and degrade gracefully.
try:
    from tradingview_ta import TA_Handler, Interval  # type: ignore
    TVA_AVAILABLE = True
except Exception:
    TA_Handler = None  # type: ignore
    Interval = None  # type: ignore
    TVA_AVAILABLE = False

# Optional local fallback using yfinance/pandas (import regardless of TVA availability)
try:
    import yfinance as yf  # type: ignore
    import pandas as pd  # type: ignore
    YF_AVAILABLE = True
except Exception:
    yf = None  # type: ignore
    pd = None  # type: ignore
    YF_AVAILABLE = False


def fetch_price(symbol_key: str) -> Optional[dict]:
    """Return latest price for logical symbol_key (e.g. 'JP225') from tradingview.jsonl.
    The function scans the file from the end (efficient enough for small files) and looks for a payload
    whose 'symbol' or 's' field matches the symbol_key or common aliases (N225, ^N225, JP225).
    """
    if not os.path.exists(TV_PATH):
        return None
    # Per-symbol alias sets to increase chance of matching webhook payloads
    ALIASES_MAP = {
        'JP225': ['JP225', 'N225', '^N225', 'JAPAN225', 'JAPAN225CFD'],
        'NQ100': ['NQ100', 'NAS100', 'NQ1!', 'NDX', 'NAS100USD'],
        'NAS100': ['NAS100', 'NQ100', 'NAS100USD'],
        'US30': ['US30', 'DJI', '^DJI', 'YM1!', 'US30USD'],
        'XAUUSD': ['XAUUSD', 'GOLD', 'XAU'],
        'XAGUSD': ['XAGUSD', 'SILVER', 'XAG'],
    }
    aliases = set(ALIASES_MAP.get(symbol_key.upper(), [symbol_key,]))
    try:
        with open(TV_PATH, 'rb') as fh:
            # read last ~50KB to find latest entries
            fh.seek(0, os.SEEK_END)
            sz = fh.tell()
            start = max(0, sz - 65536)
            fh.seek(start)
            data = fh.read().decode('utf-8', errors='ignore')
    except Exception:
        return None

    lines = [l for l in data.splitlines() if l.strip()]
    # traverse reversed to find latest matching payload
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except Exception:
            continue
        payload = entry.get('payload') or {}
        # payload may be a dict or TradingView may post plain text
        # try to extract symbol and price
        sym = None
        price = None
        if isinstance(payload, dict):
            # common keys
            for k in ('symbol', 's', 'ticker'):
                if k in payload:
                    sym = str(payload.get(k))
                    break
            for k in ('price', 'p', 'close', 'c'):
                if k in payload:
                    try:
                        price = float(payload.get(k))
                        break
                    except Exception:
                        pass
        else:
            # string case: try to parse simple JSON inside
            try:
                p2 = json.loads(payload)
                if isinstance(p2, dict):
                    payload = p2
                    for k in ('symbol', 's', 'ticker'):
                        if k in payload:
                            sym = str(payload.get(k)); break
                    for k in ('price', 'p', 'close', 'c'):
                        if k in payload:
                            try:
                                price = float(payload.get(k)); break
                            except Exception:
                                pass
            except Exception:
                pass

        if (sym and any(a.upper() in sym.upper() for a in aliases)) or (not sym and price is not None):
            return {'price': price, 'raw': entry}

    return None


def get_tv_screener_data(symbol: str, market: str, exchange: str = "OANDA",
                         interval=None) -> Optional[Dict[str, Any]]:
    """Return technicals for `symbol` using tradingview_ta if available.

    symbol: ticker string compatible with tradingview_ta (e.g. 'JP225USD', 'NQ100USD', 'XAUUSD')
    market: screener name like 'japan', 'america', 'crypto', or 'cfd'
    exchange: exchange name (CFD providers like 'OANDA')
    interval: tradingview_ta Interval (defaults to 30m if available)

    Returns dict with keys: symbol, price, SMA25, SMA75, RSI, MACD, MACD_signal, Recommend
    or None if tradingview_ta is not installed / data unavailable.
    """
    if not TVA_AVAILABLE:
        return None

    if interval is None:
        try:
            interval = Interval.INTERVAL_30_MINUTES
        except Exception:
            interval = None

    try:
        handler = TA_Handler(symbol=symbol, screener=market, exchange=exchange, interval=interval)
        analysis = handler.get_analysis()
    except Exception:
        return None

    inds = analysis.indicators if hasattr(analysis, 'indicators') else {}
    summary = analysis.summary if hasattr(analysis, 'summary') else {}

    def _get(k):
        try:
            v = inds.get(k)
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    # try a few common keys; some symbols provide slightly different SMA names
    sma25 = inds.get('SMA25') or inds.get('SMA_25') or inds.get('SMA20')
    sma75 = inds.get('SMA75') or inds.get('SMA_75') or inds.get('SMA50')
    macd = inds.get('MACD.macd') or inds.get('MACD') or inds.get('MACD_HIST')
    macd_signal = inds.get('MACD.signal') or inds.get('MACD.signal') or inds.get('MACD_signal')

    out = {
        'symbol': symbol,
        'price': _get('close') or _get('c') or _get('price') or None,
        'SMA25': float(sma25) if sma25 is not None else None,
        'SMA75': float(sma75) if sma75 is not None else None,
        'RSI': _get('RSI'),
        'MACD': float(macd) if macd is not None else None,
        'MACD_signal': float(macd_signal) if macd_signal is not None else None,
        'Recommend': summary.get('RECOMMENDATION') if isinstance(summary, dict) else None,
    }

    return out


# Simple in-process TTL cache to avoid hammering TradingView
_TVA_CACHE: Dict[tuple, Dict[str, Any]] = {}
_TVA_CACHE_TTL = int(os.getenv("TVA_CACHE_TTL", "60"))  # seconds


def get_tv_screener_data_cached(symbol: str, market: str, exchange: str = "OANDA", interval=None):
    """Cache wrapper around get_tv_screener_data with a TTL to reduce requests.

    Returns the same result as get_tv_screener_data. Cache key is (symbol, market, exchange).
    """
    key = (symbol, market, exchange)
    now = time.time()
    entry = _TVA_CACHE.get(key)
    if entry and now - entry.get("time", 0) < _TVA_CACHE_TTL:
        return entry.get("data")

    data = get_tv_screener_data(symbol, market, exchange, interval)
    _TVA_CACHE[key] = {"time": now, "data": data}
    return data


def get_tv_screener_data_auto(base_symbol: str, interval=None):
    """Try several TradingView symbol/exchange combinations for a base_symbol and return
    the first successful screener result. Uses the cached getter to avoid hammering TV.

    Returns a dict (with extra keys 'used_symbol' and 'exchange') or None.
    """
    if not TVA_AVAILABLE:
        return None

    # canonicalize
    base = base_symbol.upper()

    # fixed symbol candidate mapping (user-provided recommended defaults)
    SYMBOL_CANDIDATES = {
        # Prefer futures/continuous future symbols first for highest precision
        "JP225": [("JAPAN225CFD", "japan", "OANDA")],
        "NQ100": [("NQ1!", "america", "CME_MINI"), ("NAS100USD", "america", "OANDA")],
        # US30 (Dow Jones) prefer YM1! (Dow futures) then broker CFD / index
        "US30": [("YM1!", "america", "CME_MINI"), ("US30USD", "america", "OANDA"), ("DJI", "america", "INDEX")],
        "GER40": [("GER40EUR", "europe", "OANDA")],
        "XAUUSD": [("XAUUSD", "cfd", "OANDA")],
        "XAGUSD": [("XAGUSD", "cfd", "OANDA")],
        "NGAS": [("NGASUSD", "cfd", "OANDA")],
        # 追加: 銅先物の有力候補（TradingView の継続先物シンボル HG1! をまず試す）
        "COPPER": [("HG1!", "cfd", "TVC"), ("HG1!", "cfd", "OANDA")],
    }

    # default candidate patterns if not present in mapping
    default_candidates = [
        (base + 'USD', 'cfd', 'OANDA'),
        (base, 'cfd', 'TVC'),
        (base, 'forex', 'FX_IDC'),
    ]

    tries = SYMBOL_CANDIDATES.get(base, []) + default_candidates

    # simple base-symbol TTL cache to avoid repeated candidates trials
    try:
        _AUTO_CACHE
    except NameError:
        _AUTO_CACHE = {}
    _AUTO_TTL = int(os.getenv("TVA_AUTO_CACHE_TTL", "60"))
    cached = _AUTO_CACHE.get(base)
    if cached and time.time() - cached.get("ts", 0) < _AUTO_TTL:
        # cache hit
        # return a shallow copy to avoid accidental mutation
        return dict(cached.get("data"))

    for sym, screener, exch in tries:
        try:
            res = get_tv_screener_data(sym, screener, exch, interval) if 'get_tv_screener_data' in globals() else None
        except Exception:
            res = None
        if res:
            # attach metadata about which symbol/exchange succeeded
            res_out = dict(res) if isinstance(res, dict) else {}
            res_out['used_symbol'] = sym
            res_out['exchange'] = exch
            res_out['screener'] = screener
            # cache and return
            _AUTO_CACHE[base] = {"ts": time.time(), "data": res_out}
            return res_out

    # If TradingView attempts failed, fallback to yfinance local technicals
    if YF_AVAILABLE:
        try:
            local = get_local_technicals(base_symbol, period='7d', interval='30m')
            if local:
                # attach metadata to indicate fallback
                out = dict(local)
                out['used_symbol'] = base_symbol
                out['exchange'] = 'yfinance'
                out['screener'] = 'yfinance'
                _AUTO_CACHE[base] = {"ts": time.time(), "data": out}
                return out
        except Exception:
            pass

    return None


def get_local_technicals(symbol: str, period='7d', interval='30m'):
    """Fetch recent OHLC via yfinance and compute SMA25/SMA75/RSI/MACD as a fallback.

    Returns dict or None.
    """
    if not YF_AVAILABLE:
        return None
    try:
        # Try per-symbol preferred Yahoo tickers first, then fallbacks
        YF_CANDIDATES = {
            'JP225': ['^N225', '^NIKKEI225'],
            'NQ100': ['^NDX'],
            'GER40': ['^GDAXI'],
            'XAUUSD': ['GC=F'],
            'XAGUSD': ['SI=F'],
            'NGAS': ['NG=F'],
        }

        # Allow operator to supply overrides via environment variable to prefer ETFs or other tickers.
        # Example: export YF_SYMBOL_OVERRIDES='{"JP225": ["EWJ", "^N225"]}'
        try:
            import os as _os
            overrides_raw = _os.getenv('YF_SYMBOL_OVERRIDES')
            if overrides_raw:
                try:
                    import json as _json
                    overrides = _json.loads(overrides_raw)
                    if isinstance(overrides, dict):
                        for k, v in overrides.items():
                            if isinstance(v, list) and v:
                                YF_CANDIDATES[k.upper()] = v + YF_CANDIDATES.get(k.upper(), [])
                except Exception:
                    pass
        except Exception:
            pass

        candidates = YF_CANDIDATES.get(symbol.upper(), [symbol, symbol + '.T', symbol + 'USD', '^' + symbol])
        df = None
        symbol_used = symbol
        for s in candidates:
            try:
                df = yf.download(s, period=period, interval=interval, progress=False)
                # normalize Series -> DataFrame and ensure 'Close' exists
                if isinstance(df, pd.Series):
                    df = df.to_frame()
                if df is not None and hasattr(df, 'empty') and not df.empty:
                    # if Close column missing but there's one column, assume it's Close
                    if 'Close' not in df.columns and df.shape[1] == 1:
                        df.columns = ['Close']
                    if 'Close' in df.columns:
                        symbol_used = s
                        break
            except Exception:
                df = None
        if df is None or df.empty:
            return None

        close = df['Close']
        # If yfinance returns MultiIndex columns or a single-column DataFrame, convert to Series
        if isinstance(close, pd.DataFrame):
            # pick the last column (most specific ticker)
            close = close.iloc[:, -1]
        # SMA windows - ensure enough data
        sma25 = close.rolling(window=25, min_periods=1).mean().iloc[-1]
        sma75 = close.rolling(window=75, min_periods=1).mean().iloc[-1]

        # RSI calculation (14 period)
        delta = close.diff()
        up = delta.clip(lower=0).rolling(window=14, min_periods=1).mean()
        down = -delta.clip(upper=0).rolling(window=14, min_periods=1).mean()
        rs = up / down.replace(0, 1e-9)
        rsi = 100 - (100 / (1 + rs)).iloc[-1]

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_val = macd.iloc[-1]
        macd_signal = macd.ewm(span=9, adjust=False).mean().iloc[-1]

        recommend = "STRONG_BUY" if rsi < 30 else "STRONG_SELL" if rsi > 70 else "NEUTRAL"

        return {
            "source": "yfinance",
            "price": float(close.iloc[-1]),
            "SMA25": round(float(sma25), 2),
            "SMA75": round(float(sma75), 2),
            "RSI": round(float(rsi), 2),
            "MACD": round(float(macd_val), 2),
            "MACD_signal": round(float(macd_signal), 2),
            "Recommend": recommend,
            "symbol_used": symbol_used,
        }
    except Exception as e:
        print(f"⚠️ Local technicals fetch failed for {symbol}: {e}")
        return None


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: market_data_tradingview.py SYMBOL_KEY')
        sys.exit(2)
    res = fetch_price(sys.argv[1])
    print(json.dumps(res, ensure_ascii=False, indent=2))
