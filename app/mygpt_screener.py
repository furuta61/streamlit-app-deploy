from __future__ import annotations
import time
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from .config import TV, LOGGER, YF_SYMBOL_OVERRIDES

# optional tradingview_ta
try:
    from tradingview_ta import TA_Handler, Interval
    _TV_AVAILABLE = True
except Exception:
    _TV_AVAILABLE = False


# optional GMO realtime
try:
    from .datafeed.gmo_realtime import GMORealtimeClient
    _GMO_AVAILABLE = True
except Exception:
    _GMO_AVAILABLE = False


# ─────────────────────────────────────────────
# TTL cache（主に TV / yfinance 用。GMOはリアルタイムなのでキャッシュしない）
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# TradingView 用のラッパー
# ─────────────────────────────────────────────
def _get_tv_screener(
    symbol: str,
    screener: str,
    exchange: str,
    interval: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not _TV_AVAILABLE:
        return None
    try:
        interval_map = {
            None:   Interval.INTERVAL_30_MINUTES,
            "30m":  Interval.INTERVAL_30_MINUTES,
            "1h":   Interval.INTERVAL_1_HOUR,
            "4h":   Interval.INTERVAL_4_HOURS,
            "1d":   Interval.INTERVAL_1_DAY,
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
            # TVはSMA75が無いことが多いので、50/100/200 を候補として使う
            "SMA75": ind.get("SMA75") or ind.get("SMA50") or ind.get("SMA100") or ind.get("SMA200"),
            "RSI": ind.get("RSI"),
            "MACD": ind.get("MACD.macd"),
            "MACD_signal": ind.get("MACD.signal"),
            "ATR": None,
            "Recommend": rec or "NEUTRAL",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        return out
    except Exception as e:
        # Inspect the error message and handle common TradingView failure modes quietly:
        #  - rate limiting (HTTP 429 / Too Many Requests) -> info and fall back to next source
        #  - symbol/exchange not found -> warning and fall back
        msg = str(e)
        low = msg.lower()
        if "429" in msg or "too many requests" in low or "can't access tradingview" in low:
            LOGGER.info("tradingview_ta rate limited for %s/%s: %s", screener, symbol, msg)
            return None
        if "symbol not found" in low or "exchange or symbol not found" in low or "exchange or symbol" in low:
            LOGGER.warning("tradingview_ta symbol/exchange not found for %s/%s: %s", screener, symbol, msg)
            return None
        # Fallback: log full exception for unexpected errors
        LOGGER.exception("tradingview_ta error for %s/%s: %s", screener, symbol, msg)
        return None


# ─────────────────────────────────────────────
# 対象銘柄マッピング（TV と yfinance）
# ─────────────────────────────────────────────
TV_CANDIDATES: Dict[str, list[tuple[str, str, str]]] = {
    "JP225": [
        ("JP225USD", "japan", "OANDA"),
        ("N225", "japan", "FX_IDC"),
        ("JP225", "japan", "TVC"),
        ("JAPAN225CFD", "japan", "OANDA"),
    ],
    "NQ100": [
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
    # US30 は今後使わない想定だが、互換性のために残しておいても良い
    "US30": [
        ("YM1!", "america", "CME_MINI"),
        ("US30USD", "america", "OANDA"),
        ("DJI", "america", "INDEX"),
    ],
}

YF_TICKERS: Dict[str, str] = {
    "JP225": "^N225",
    "NQ100": "^NDX",
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
    "NGAS":  "NG=F",
    "GER40": "^GDAXI",   # ← ここが今回追加
    "US30":  "^DJI",
}


# ─────────────────────────────────────────────
# ローカルテクニカル計算（yfinance用）
# ─────────────────────────────────────────────
def _calc_rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    rs = (up.rolling(period).mean() / down.rolling(period).mean()).iloc[-1]
    if rs is None or rs == 0:
        return None
    return float(100 - 100 / (1 + rs))

def _calc_macd(close: pd.Series) -> tuple[Optional[float], Optional[float]]:
    if len(close) < 26:
        return (None, None)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    return (float(macd_line.iloc[-1]), float(signal.iloc[-1]))

def _calc_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    if not set(["High", "Low", "Close"]).issubset(df.columns):
        return None
    if len(df) < period + 1:
        return None
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

    atr = None
    try:
        atr = _calc_atr(df, 14)
    except Exception:
        atr = None
    if atr is None and len(close) >= 14:
        # 簡易ATR近似（ボラが完全に欲しい訳ではないので妥協）
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


# ─────────────────────────────────────────────
# yfinance フォールバック
# ─────────────────────────────────────────────
def _get_yf_screener(
    base_symbol: str,
    period: str = "14d",
    interval: str = "30m",
) -> Optional[Dict[str, Any]]:
    yf_sym = None
    try:
        # config で上書きがあれば優先
        if 'YF_SYMBOL_OVERRIDES' in globals() and YF_SYMBOL_OVERRIDES:
            yf_sym = YF_SYMBOL_OVERRIDES.get(base_symbol)
    except Exception:
        yf_sym = None

    if yf_sym is None:
        yf_sym = YF_TICKERS.get(base_symbol)

    if not yf_sym:
        LOGGER.warning("yfinance ticker not mapped for %s", base_symbol)
        return None

    try:
        df = yf.download(
            yf_sym,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )

        if df is None:
            LOGGER.warning("yfinance returned None for %s (%s)", base_symbol, yf_sym)
            return None
        if hasattr(df, "empty") and bool(df.empty):
            LOGGER.warning("yfinance returned empty df for %s (%s)", base_symbol, yf_sym)
            return None

        # ★ MultiIndex カラム対応（^N225 など）
        if isinstance(df.columns, pd.MultiIndex):
            try:
                # よくあるパターン:
                #  - level0=Price label (Close/Open/High/Low), level1=Ticker  => columns like ("Close","^N225")
                #  - 逆パターンで level0=Ticker, level1=Price  => columns like ("^N225","Close")
                lvl0 = list(df.columns.get_level_values(0))
                lvl1 = list(df.columns.get_level_values(1))

                if "Close" in lvl0:
                    # level0 に Close がある場合はそこを抽出
                    try:
                        df = df.xs("Close", axis=1, level=0)
                        LOGGER.info("xs('Close', level=0) flattened MultiIndex df for %s (%s). cols=%s",
                                    base_symbol, yf_sym, list(df.columns))
                    except Exception:
                        pass
                elif "Close" in lvl1:
                    try:
                        df = df.xs("Close", axis=1, level=1)
                        LOGGER.info("xs('Close', level=1) flattened MultiIndex df for %s (%s). cols=%s",
                                    base_symbol, yf_sym, list(df.columns))
                    except Exception:
                        pass
                elif yf_sym in lvl0:
                    try:
                        df = df.xs(yf_sym, axis=1, level=0)
                        LOGGER.info("xs(yf_sym, level=0) flattened MultiIndex df for %s (%s). cols=%s",
                                    base_symbol, yf_sym, list(df.columns))
                    except Exception:
                        pass
                elif yf_sym in lvl1:
                    try:
                        df = df.xs(yf_sym, axis=1, level=1)
                        LOGGER.info("xs(yf_sym, level=1) flattened MultiIndex df for %s (%s). cols=%s",
                                    base_symbol, yf_sym, list(df.columns))
                    except Exception:
                        pass
                else:
                    # 最後の手段: タプル要素に 'close' を含むカラムを探す -> それを Close とみなす
                    found = None
                    for c in df.columns:
                        try:
                            if isinstance(c, tuple) and any("close" in str(x).lower() for x in c):
                                found = c
                                break
                        except Exception:
                            continue
                    if found is not None:
                        df = df[[found]]
                        df.columns = ["Close"]
                        LOGGER.info("picked tuple column as Close fallback for %s (%s): %s", base_symbol, yf_sym, found)
                    else:
                        LOGGER.warning("MultiIndex fallback: cannot find Close for %s (%s). levels=%s cols=%s",
                                       base_symbol, yf_sym, df.columns.names, list(df.columns))
                        # それでも見つからなければ行末の数値を取りに行く（テクニカルは計算できないが価格は取れる可能性あり）
                        last_row = df.tail(1)
                        vals = []
                        try:
                            # flatten row values and pick last non-null numeric
                            for v in last_row.iloc[0].values:
                                try:
                                    if v is None or (isinstance(v, float) and pd.isna(v)):
                                        continue
                                    vals.append(float(v))
                                except Exception:
                                    continue
                        except Exception:
                            vals = []
                        if vals:
                            last_price = vals[-1]
                            out = {
                                "source": "yfinance",
                                "symbol_used": yf_sym,
                                "screener": "yfinance",
                                "exchange": "yahoo",
                                "price": float(last_price),
                                "SMA25": None,
                                "SMA75": None,
                                "RSI": None,
                                "MACD": None,
                                "MACD_signal": None,
                                "ATR": None,
                                "Recommend": "NEUTRAL",
                                "fetched_at": datetime.now(timezone.utc).isoformat() + "Z",
                            }
                            return out
                        else:
                            LOGGER.warning("Unable to extract numeric fallback price for %s (%s)", base_symbol, yf_sym)
                            return None
            except Exception as e:
                LOGGER.error("failed to flatten MultiIndex df for %s (%s): %s",
                             base_symbol, yf_sym, e)

        # ここから先は単一カラムを想定
        # MultiIndex flatten の後に、カラム名がティッカー（'^N225' など）になっている場合がある。
        # そのときは該当ティッカー列を Close にリネームして扱ってみる。
        try:
            cols_list = list(df.columns)
            renamed = False
            for i, c in enumerate(cols_list):
                try:
                    if str(c) == str(yf_sym) or (isinstance(c, str) and c.endswith(str(yf_sym))):
                        cols_list[i] = "Close"
                        renamed = True
                except Exception:
                    continue
            if renamed:
                df.columns = cols_list
                LOGGER.info("renamed ticker-like column to Close for %s (%s). cols=%s", base_symbol, yf_sym, list(df.columns))
        except Exception:
            pass

        if "Close" not in df.columns:
            LOGGER.warning("yfinance df has no Close column for %s (%s). cols=%s",
                           base_symbol, yf_sym, list(df.columns))
            return None

        close = df["Close"]
        close = close.dropna().astype(float)
        if len(close) == 0:
            LOGGER.warning("yfinance Close series empty for %s (%s)", base_symbol, yf_sym)
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
        LOGGER.error("yfinance error for %s (%s): %s", base_symbol, yf_sym, e)
        return None


# ─────────────────────────────────────────────
# GMOクリック CFD リアルタイムクライアント（遅延起動）
# ─────────────────────────────────────────────
_gmo_client: Optional["GMORealtimeClient"] = None
_gmo_init_failed = False

def _get_gmo_client() -> Optional["GMORealtimeClient"]:
    global _gmo_client, _gmo_init_failed
    if not _GMO_AVAILABLE:
        return None
    if _gmo_init_failed:
        return None
    if _gmo_client is None:
        try:
            # ここで扱いたいシンボルを列挙（JP225 / NQ100 / XAUUSD / GER40）
            _gmo_client = GMORealtimeClient(["JP225", "NQ100", "XAUUSD", "GER40"])
            _gmo_client.start()
            LOGGER.info("GMORealtimeClient started for JP225/NQ100/XAUUSD/GER40")
        except Exception:
            _gmo_init_failed = True
            LOGGER.exception("failed to init GMORealtimeClient")
            return None
    return _gmo_client


# ─────────────────────────────────────────────
# 公開関数：GMO → TV → yfinance の3段構成スクリーナー
# ─────────────────────────────────────────────
def get_screener_auto(base_symbol: str, interval: Optional[str] = "30m") -> Optional[Dict[str, Any]]:
    """
    優先順:
      1. GMOクリック CFD のリアルタイム（利用可能な場合）
      2. TradingView (tradingview_ta)
      3. yfinance ローカル計算

    ※ 戻り値のキー:
      - price, SMA25, SMA75, RSI, MACD, MACD_signal, ATR, Recommend, fetched_at, source, symbol_used, screener, exchange
    """
    # 1️⃣ GMOリアルタイム（価格のみだが、最新値としては最優先）
    gmo = _get_gmo_client()
    if gmo is not None:
        try:
            gmo_tick = gmo.get_price(base_symbol)
            if gmo_tick and "bid" in gmo_tick:
                # GMOリクだけでテクニカルは足りないので、
                # この時点では price だけを埋めて他は None にする。
                # （テクニカルは CSV/別レイヤーで計算して使う想定）
                return {
                    "source": "gmo_realtime",
                    "symbol_used": base_symbol,
                    "screener": "GMO",
                    "exchange": "GMO_CLICK",
                    "price": float(gmo_tick["bid"]),
                    "SMA25": None,
                    "SMA75": None,
                    "RSI": None,
                    "MACD": None,
                    "MACD_signal": None,
                    "ATR": None,
                    "Recommend": "NEUTRAL",
                    "fetched_at": gmo_tick.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                }
        except Exception:
            LOGGER.exception("GMORealtimeClient get_price failed for %s", base_symbol)

    # 2️⃣ TradingView（やや重いのでTTLキャッシュを使う）
    key = f"scr::{base_symbol}::{interval}"
    cached = _ttl_get(key)
    if cached:
        return cached

    # TV候補を順番に試す
    for sym, scr, exch in TV_CANDIDATES.get(base_symbol, []):
        tv = _get_tv_screener(sym, scr, exch, interval)
        if tv and tv.get("price") is not None:
            _ttl_set(key, tv)
            return tv

    # 3️⃣ yfinance フォールバック
    yf_res = _get_yf_screener(base_symbol)
    if yf_res:
        _ttl_set(key, yf_res)
        return yf_res

    # それでもダメなら None
    LOGGER.warning("get_screener_auto: no data source succeeded for %s", base_symbol)
    return None

# 使い方イメージ
if __name__ == "__main__":
    from pprint import pprint
    for s in ("JP225", "NQ100", "XAUUSD", "GER40"):
        print(s)
        pprint(get_screener_auto(s, "30m"))
