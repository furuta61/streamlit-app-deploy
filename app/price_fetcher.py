"""app/price_fetcher.py
Simple wrapper around yfinance (and fallbacks) to provide current price/bid/ask.
Designed to be small and dependency-light; can be extended to call OANDA/TwelveData later.
"""
from datetime import datetime
import time
import yfinance as yf
from .config import YF_SYMBOL_OVERRIDES


def _yf_symbol(symbol: str) -> str:
    return YF_SYMBOL_OVERRIDES.get(symbol, symbol)


def fetch_price(symbol: str) -> dict:
    """Fetch last available price for symbol using yfinance.

    Returns: { 'symbol': symbol, 'price': float, 'bid': float, 'ask': float, 'timestamp': iso }
    """
    yf_sym = _yf_symbol(symbol)
    try:
        t = yf.Ticker(yf_sym)
        # try fast path: use info if available
        info = t.info if hasattr(t, 'info') else {}
    except Exception:
        info = {}

    # last close from history
    try:
        hist = t.history(period='1d', interval='1m')
        if hist is None or hist.empty:
            # fallback to 1d daily
            hist = t.history(period='5d', interval='1d')
        last = float(hist['Close'].iloc[-1])
    except Exception:
        last = info.get('regularMarketPrice') or info.get('previousClose') or None

    # bid/ask best-effort (yfinance may not provide)
    bid = info.get('bid') or info.get('bidPrice') or last
    ask = info.get('ask') or info.get('askPrice') or last

    ts = datetime.utcnow().isoformat()
    return {
        'symbol': symbol,
        'yf_symbol': yf_sym,
        'price': float(last) if last is not None else None,
        'bid': float(bid) if bid is not None else None,
        'ask': float(ask) if ask is not None else None,
        'timestamp': ts,
        'source': 'yfinance',
    }


if __name__ == '__main__':
    # quick manual test
    for s in ['JP225', 'NQ100', 'XAUUSD', 'XAGUSD', 'NGAS', 'GER40']:
        print(fetch_price(s))
        time.sleep(0.5)
