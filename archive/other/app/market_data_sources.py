from __future__ import annotations
import time
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf
from .config import TV, LOGGER, YF_SYMBOL_OVERRIDES
# Optional GMO realtime datafeed (non-fatal if unavailable)
try:
    from app.datafeed.gmo_realtime import GMORealtimeClient
    _gmo_client = GMORealtimeClient(["JP225", "NQ100", "XAUUSD", "GER40"])
    # start background connection; if websocket-client not installed this may raise
    try:
        _gmo_client.start()
    except Exception:
        # non-fatal: run without GMO feed
        _gmo_client = None
except Exception:
    _gmo_client = None

# optional tradingview_ta
try:
    from tradingview_ta import TA_Handler, Interval
    _TV_AVAILABLE = True
except Exception:
    _TV_AVAILABLE = False

# ── TTL cache ───────────────────────────────────────────────
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

def _ttl_get(key: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    if key in _cache:
        ts, val = _cache[key]
        if now - ts <= TV.tv_cache_ttl_sec:
            return val
    return None

def _ttl_set(key: str, val: Dict[str, Any]):
    _cache[key] = (time.time(), val)

# ── TradingView via tradingview_ta ──────────────────────────
def _get_tv_screener(symbol: str, screener: str, exchange: str, interval: Optional[str]) -> Optional[Dict[str, Any]]:
    if not _TV_AVAILABLE:
        return None
    try:
        interval_map = {
            None: Interval.INTERVAL_30_MINUTES,
            "30m": Interval.INTERVAL_30_MINUTES,
            "1h": Interval.INTERVAL_1_HOUR,
            "4h": Interval.INTERVAL_4_HOURS,
            "1d": Interval.INTERVAL_1_DAY,
        }
        i = interval_map.get(interval, Interval.INTERVAL_30_MINUTES)
        h = TA_Handler(symbol=symbol, screener=screener, exchange=exchange, interval=i)
        analysis = h.get_analysis()
        ind = analysis.indicators or {}
        rec = (analysis.summary or {}).get("RECOMMENDATION")

        out = {
            "source": "tradingview",
            "symbol_used": symbol,
            "screener": screener,
            "exchange": exchange,
            "price": ind.get("close"),
            "SMA25": ind.get("SMA25"),
            "SMA75": ind.get("SMA50") or ind.get("SMA100") or ind.get("SMA200"),
            "RSI": ind.get("RSI"),
            "MACD": ind.get("MACD.macd"),
            "MACD_signal": ind.get("MACD.signal"),
            "ATR": None,
            "Recommend": rec or "NEUTRAL",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        return out
    except Exception:
        return None

TV_CANDIDATES = {
    "JP225": [
        ("JP225USD", "japan", "OANDA"),
        ("N225", "japan", "FX_IDC"),
        ("JP225", "japan", "TVC"),
        ("JAPAN225CFD", "japan", "OANDA"),
    ],
    "NQ100": [
        # Prefer CME mini/e-mini continuous future for highest real-time precision,
        # then broker CFD listing, then index ticker as fallback.
        ("NQ1!", "america", "CME_MINI"),
        ("NAS100USD", "america", "OANDA"),
        ("NDX", "america", "NASDAQ"),
    ],
    "XAUUSD": [
        ("XAUUSD", "cfd", "OANDA"),
        ("XAUUSD", "forex", "OANDA"),
        ("GOLD", "cfd", "TVC"),
    ],
    "XAGUSD": [
        ("XAGUSD", "cfd", "OANDA"),
        ("SILVER", "cfd", "TVC"),
    ],
    "NGAS": [
        ("NATGASUSD", "cfd", "OANDA"),
        ("NG1!", "america", "NYMEX"),
    ],
    "GER40": [
        ("DE40EUR", "cfd", "OANDA"),
        ("GER40", "cfd", "TVC"),
        ("DAX", "germany", "XETR"),
    ],
    # Add US30 (Dow Jones) candidates: prefer futures (YM1!) then broker CFD / index
    "US30": [
        ("YM1!", "america", "CME_MINI"),
        ("US30USD", "america", "OANDA"),
        ("DJI", "america", "INDEX"),
    ],
}

YF_TICKERS = {
    "JP225": "^N225",
    "NQ100": "^NDX",
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
    "NGAS":  "NG=F",
    "GER40": "^GDAXI",
}

def _calc_rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    if len(close) < period + 1: return None
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    rs = (up.rolling(period).mean() / down.rolling(period).mean()).iloc[-1]
    if rs is None or rs == 0: return None
    return float(100 - 100 / (1 + rs))

def _calc_macd(close: pd.Series) -> tuple[Optional[float], Optional[float]]:
    if len(close) < 26: return (None, None)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    return (float(macd_line.iloc[-1]), float(signal.iloc[-1]))

def _calc_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    if not set(["High","Low","Close"]).issubset(df.columns): return None
    if len(df) < period + 1: return None
    high = df["High"].astype(float)
    low  = df["Low"].astype(float)
    close= df["Close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if pd.notnull(atr) else None

def _local_technicals_from_df(df: pd.DataFrame) -> Dict[str, Any]:
    # Use explicit emptiness/length checks; avoid boolean evaluation of Series
    close = df.get("Close")
    if close is None:
        return {"SMA25": None, "SMA75": None, "RSI": None, "MACD": None, "MACD_signal": None, "ATR": None}
    close = close.dropna().astype(float)
    if close.empty:
        return {"SMA25": None, "SMA75": None, "RSI": None, "MACD": None, "MACD_signal": None, "ATR": None}

    sma25 = close.rolling(25).mean().iloc[-1] if len(close) >= 25 else None
    sma75 = close.rolling(75).mean().iloc[-1] if len(close) >= 75 else None
    rsi = _calc_rsi(close, 14)
    macd, macd_sig = _calc_macd(close)
    # Prefer ATR from OHLC if available, otherwise approximate from close pct std
    atr = None
    try:
        atr = _calc_atr(df, 14)
    except Exception:
        atr = None
    if atr is None and len(close) >= 14:
        # approximate ATR using rolling std of returns scaled by price
        last_price = float(close.iloc[-1])
        try:
            pct_std = close.pct_change().rolling(14).std().iloc[-1]
            if pd.notnull(pct_std):
                atr = float(pct_std * last_price * 1.5)
        except Exception:
            atr = None

    return {
        "SMA25": float(sma25) if sma25 is not None and pd.notnull(sma25) else None,
        "SMA75": float(sma75) if sma75 is not None and pd.notnull(sma75) else None,
        "RSI": float(rsi) if rsi is not None else None,
        "MACD": float(macd) if macd is not None else None,
        "MACD_signal": float(macd_sig) if macd_sig is not None else None,
        "ATR": float(atr) if atr is not None else None,
    }

def _get_yf_screener(base_symbol: str, period="14d", interval="30m") -> Optional[Dict[str, Any]]:
    # Allow config-based overrides to prefer spot/index tickers over futures
    yf_sym = YF_SYMBOL_OVERRIDES.get(base_symbol) if 'YF_SYMBOL_OVERRIDES' in globals() else None
    if yf_sym is None:
        yf_sym = YF_TICKERS.get(base_symbol)
    if not yf_sym:
        LOGGER.warning(f"yfinance ticker not mapped for {base_symbol}")
        return None
    try:
        df = yf.download(yf_sym, period=period, interval=interval, progress=False, auto_adjust=True)
        if df is None or (hasattr(df, 'empty') and df.empty):
            return None

        # Close を series として取得し、真偽値判定をしない
        close = df.get("Close")
        if close is None:
            return None
        close = close.dropna().astype(float)
        if close.empty:
            return None

        last_price = float(close.iloc[-1])
        tech = _local_technicals_from_df(df)
        out = {
            "source": "yfinance",
            "symbol_used": yf_sym,
            "screener": "yfinance",
            "exchange": "yahoo",
            "price": last_price,
            **tech,
            "Recommend": "NEUTRAL",
            "fetched_at": datetime.now(timezone.utc).isoformat() + "Z",
        }
        return out
    except Exception as e:
        LOGGER.error(f"yfinance error for {base_symbol}: {e}")
        return None

def get_screener_auto(base_symbol: str, interval: Optional[str]="30m") -> Optional[Dict[str, Any]]:
    """Try GMO realtime -> TV candidates -> fallback yfinance. Cached."""
    # 1) GMO realtime (if available)
    try:
        if _gmo_client:
            gmo_price = _gmo_client.get_price(base_symbol)
            if gmo_price:
                return {
                    "source": "gmo_realtime",
                    "symbol_used": base_symbol,
                    "screener": "GMO",
                    "exchange": "GMO_CLICK",
                    "price": gmo_price.get("bid"),
                    "SMA25": None,
                    "SMA75": None,
                    "RSI": None,
                    "MACD": None,
                    "MACD_signal": None,
                    "ATR": None,
                    "Recommend": "NEUTRAL",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
    except Exception:
        # ignore GMO feed errors and continue
        pass

    # 2) cached TV / tradingview
    key = f"scr::{base_symbol}::{interval}"
    cached = _ttl_get(key)
    if cached:
        return cached

    for sym, scr, exch in TV_CANDIDATES.get(base_symbol, []):
        tv = _get_tv_screener(sym, scr, exch, interval)
        if tv:
            _ttl_set(key, tv)
            return tv

    # 3) yfinance fallback
    yfres = _get_yf_screener(base_symbol)
    if yfres:
        _ttl_set(key, yfres)
        return yfres

    return None
