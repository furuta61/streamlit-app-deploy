from __future__ import annotations
# app/config.py
"""
Symbol-specific configuration: decimal places, TP/SL ratios, and YFinance overrides.
This file centralizes rounding and symbol mappings used by the auto-fill pipeline.
"""

YF_SYMBOL_OVERRIDES = {
    # map our canonical symbols to yfinance symbols when they differ
    "JP225": "^N225",
    "NQ100": "^NDX",
    "GER40": "^GDAXI",
    # prefer futures for better availability on yfinance
    "XAUUSD": "GC=F",  # Gold Futures
    "XAGUSD": "SI=F",  # Silver Futures
    "NGAS":  "NG=F",   # Natural Gas Futures
}

# Per-symbol rounding and TP/SL percentage rules (fractions, e.g. 0.015 = +1.5%)
SYMBOL_SETTINGS = {
    "JP225": {"decimals": 0, "tp1": 0.015, "tp2": 0.025, "sl": -0.03, "order_type": "LIMIT"},
    "NQ100": {"decimals": 0, "tp1": 0.02,  "tp2": 0.03,  "sl": -0.015, "order_type": "LIMIT"},
    "GER40": {"decimals": 0, "tp1": 0.018, "tp2": 0.03,  "sl": -0.02,  "order_type": "LIMIT"},
    "XAGUSD":{"decimals": 2, "tp1": 0.025, "tp2": 0.04,  "sl": -0.012, "order_type": "LIMIT"},
    "NGAS":  {"decimals": 3, "tp1": 0.03,  "tp2": 0.06,  "sl": -0.015, "order_type": "MARKET"},
    "XAUUSD":{"decimals": 2, "tp1": 0.015, "tp2": 0.03,  "sl": -0.008, "order_type": "LIMIT"},
}

DEFAULT_DECIMALS = 2

import os
import logging
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass

# ========= Settings =========

@dataclass
class EmailConfig:
    # Support both ALERT_EMAIL_FROM and ALERT_EMAIL_USER for historical .env compatibility
    from_addr: str | None = os.getenv("ALERT_EMAIL_FROM") or os.getenv("ALERT_EMAIL_USER")
    # to_addr may be ALERT_EMAIL_TO or ALERT_EMAIL_RECIPIENT in some configs
    to_addr: str | None = os.getenv("ALERT_EMAIL_TO") or os.getenv("ALERT_EMAIL_RECIPIENT")
    # app_password accepts ALERT_EMAIL_PASS or GMAIL_APP_PASSWORD for fallback
    app_password: str | None = os.getenv("ALERT_EMAIL_PASS") or os.getenv("GMAIL_APP_PASSWORD")
    # SMTP host/port allow ALERT_EMAIL_HOST/ALERT_EMAIL_PORT or generic SMTP_HOST/SMTP_PORT
    smtp_host: str = os.getenv("ALERT_EMAIL_HOST") or os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("ALERT_EMAIL_PORT") or os.getenv("SMTP_PORT", "465"))  # SSL


@dataclass
class TradingViewConfig:
    check_interval_sec: int = int(os.getenv("CHECK_INTERVAL", "3"))
    # Increase default TV cache TTL to reduce TradingView rate-limit (429) noise.
    # Can be overridden with env TVA_AUTO_CACHE_TTL.
    tv_cache_ttl_sec: int = int(os.getenv("TVA_AUTO_CACHE_TTL", "300"))
    tv_symbol_map_json: str | None = os.getenv("TV_SYMBOL_MAP_JSON")


@dataclass
class DecisionThresholds:
    strong_go: float = float(os.getenv("THRESH_STRONG_GO", "6.0"))
    go: float = float(os.getenv("THRESH_GO", "4.0"))


@dataclass
class Paths:
    tradingview_log: str = os.getenv("TRADINGVIEW_LOG", "output/tradingview.jsonl")
    ifd_output: str = os.getenv("IFD_OUTPUT", "output/ifd_orders.jsonl")
    processed_cache: str = os.getenv("PROCESSED_CACHE", "output/.processed_cache.json")
    suppression_cache: str = os.getenv("SUPPRESSION_CACHE", "output/.suppression_cache.json")
    system_log: str = os.getenv("SYSTEM_LOG", "output/system.log")

EMAIL = EmailConfig()
TV = TradingViewConfig()
TH = DecisionThresholds()
PATH = Paths()


@dataclass
class ReliabilityConfig:
    # 入力が古いとみなす閾値（秒）
    stale_input_sec: int = int(os.getenv("STALE_INPUT_SEC", "300"))
    # 同一判断サプレッションのウィンドウ（秒）
    suppression_window_sec: int = int(os.getenv("SUPPRESSION_WINDOW_SEC", "600"))
    # ウィンドウ内での最大許容生成回数。超えるとサプレッションする
    suppression_max_count: int = int(os.getenv("SUPPRESSION_MAX_COUNT", "2"))
    # incoming price と screener price の乖離がこの比率を超えたら screener を優先する（例: 0.005 = 0.5%）
    price_mismatch_pct: float = float(os.getenv("PRICE_MISMATCH_PCT", "0.005"))


REL = ReliabilityConfig()

# 追加候補（運用での観測に基づく推奨）: 主要ティッカーの便宜上書き
YF_SYMBOL_OVERRIDES.update({
    "US30": "^DJI",      # ダウ平均
    "USDJPY": "JPY=X",   # 為替
    "GBPUSD": "GBPUSD=X",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
    "USOIL": "CL=F",     # 原油（先物）
})

# ========= Logger =========

def setup_logger():
    logger = logging.getLogger("CFD3")
    if logger.handlers:
        return logger  # avoid duplicate handlers on reload
    logger.setLevel(logging.INFO)
    os.makedirs(os.path.dirname(PATH.system_log), exist_ok=True)

    fh = RotatingFileHandler(PATH.system_log, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
    ch = logging.StreamHandler()

    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger

LOGGER = setup_logger()
