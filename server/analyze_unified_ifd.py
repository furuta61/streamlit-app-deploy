# Part 1/5: analyze_unified_ifd.py
# (This is a placeholder skeleton. Full implementation needs all 5 parts.)


import pandas as pd
import numpy as np
from pathlib import Path
import math
import os


# --- Global constants ---
POINT_VALUE_JPY = {
    "JP225": 100,
    "NAS100": 20,
    "GER40": 25,
    "XAUUSD": 100
}


# News normalization


def normalize_news(symbol, raw):
    pos = float(raw.get("positive", 50))
    neg = float(raw.get("negative", 50))
    s = raw.get("summary", "") or ""
    if pos + neg == 0:
        direction = "neutral"
    elif pos > neg:
        direction = "buy"
    elif neg > pos:
        direction = "sell"
    else:
        direction = "neutral"
    return {"positive":pos, "negative":neg, "summary":s, "direction":direction}


# Short comment generator


def short_comment(text):
    return text[:22]


# Vote aggregation


def vote_direction(votes):
    b = votes.get("buy",0)
    s = votes.get("sell",0)
    if b > s: return "buy", b
    if s > b: return "sell", s
    return "neutral", b


# Sync gate (placeholder)


def sync_ok(item):
    return True


# Regime detection


def detect_regime(t30, t240):
    if abs(t30["sma25"] - t30["sma75"]) < 0.0003 * t30["sma25"]:
        return "range"
    if t240["sma25"] > t240["sma75"]:
        return "up"
    return "down"


# === Part 3: Core decision engine ===


RR_RULE = {"range":1.2, "up":1.5, "down":1.5}
RR_STRONG = {"range":1.8, "up":2.0, "down":2.0}


GO_LOTS = 2
STRONG_LOTS = 5




def calc_rr(entry, sl, tp, side):
    if side == "buy":
        risk = max(entry - sl, 1e-9)
        reward = max(tp - entry, 0.0)
    else:
        risk = max(sl - entry, 1e-9)
        reward = max(entry - tp, 0.0)
    return reward / risk if risk > 0 else 0




def decide_level(votes, rr, regime):
    b = votes.get("buy",0)
    s = votes.get("sell",0)
    direction = "buy" if b > s else "sell"


    if rr >= RR_STRONG[regime] and max(b,s) >= 3:
        return "STRONG_GO", STRONG_LOTS, direction
    if rr >= RR_RULE[regime] and max(b,s) >= 2:
        return "GO", GO_LOTS, direction
    return "WAIT", 0, direction




def build_ifd(direction, price, atr):
    if direction == "buy":
        return price, price - atr, price + 2*atr, price + 3*atr
    else:
        return price, price + atr, price - 2*atr, price - 3*atr


# === Part 4: CUT条件生成・ニュース統合・テーブル構築 ===


def build_cut(t30, t240):
    s1 = f"SMA25<{t240['sma75']:.2f}" if t240['sma25'] < t240['sma75'] else f"SMA25>{t240['sma75']:.2f}"
    s2 = "MACD<Signal" if t30['macd'] < t30['signal'] else "MACD>Signal"
    return f"{s1} or {s2}"




def build_day6h_row(sym, decision, lots, entry, sl, tp1, tp2, news_dir, cut, comment):
    stars = "★★★★★" if decision == "STRONG_GO" else "★★★☆☆" if decision == "GO" else "★★☆☆☆"
    return {
        "trade_mode":"DAY6H",
        "symbol":sym,
        "direction":decision.lower(),
        "entry_price":round(entry,2),
        "sl":round(sl,2),
        "tp1":round(tp1,2),
        "tp2":round(tp2,2),
        "order_type":"指値",
        "判定":decision,
        "news_dir":news_dir,
        "stars":stars,
        "lots":lots,
        "cut":cut,
        "comment":comment
    }


# === Part 5: Main analysis function (placeholder for symbol loop) ===


def analyze_symbol(code, price, t30, t240, news):
    """Single symbol analysis - returns DAY6H row"""
    atr = (t30.get("atr", 0) + t240.get("atr", 0)) / 2
    if atr <= 0:
        atr = price * 0.01
    
    entry, sl, tp1, tp2 = build_ifd("buy", price, atr)  # temp; real dir below

    votes = {"buy":0, "sell":0}
    votes["buy"] += 1 if t240['sma25']>t240['sma75'] else 0
    votes["buy"] += 1 if t30['macd']>t30['signal'] else 0
    votes["buy"] += 1 if news['direction']=="buy" else 0
    votes["sell"] += 1 if news['direction']=="sell" else 0

    regime = detect_regime(t30, t240)
    sample_rr = calc_rr(price, price-atr, price+2*atr, "buy")
    decision, lots, dir = decide_level(votes, sample_rr, regime)

    entry, sl, tp1, tp2 = build_ifd(dir, price, atr)
    cut = build_cut(t30, t240)
    comment = short_comment(news['summary'] or decision)

    return build_day6h_row(code, decision, lots, entry, sl, tp1, tp2, news['direction'], cut, comment)


# === Main entry point ===


def analyze_unified_ifd(mode="DAY6H", gmo_prices=None, tech_map=None, news_map=None):
    """
    Main analysis function - returns list of DAY6H rows
    
    Args:
        mode: Trade mode (currently only "DAY6H")
        gmo_prices: Dict of {symbol: price} from Vision OCR
        tech_map: Dict of {code: (t30, t240, df30)}
        news_map: Dict of {symbol: news_data}
    
    Returns:
        List of DAY6H row dictionaries
    """
    if gmo_prices is None:
        gmo_prices = {}
    if tech_map is None:
        tech_map = {}
    if news_map is None:
        news_map = {}
    
    # Symbol mapping
    symbol_map = {
        "日本225": "JP225",
        "米国NQ100ミニ": "NAS100",
        "ドイツ40": "GER40",
        "金スポット": "XAUUSD"
    }
    
    rows = []
    
    for jp_name, code in symbol_map.items():
        # Get price from Vision OCR
        price = gmo_prices.get(jp_name)
        if price is None:
            continue
        
        # Get technical data
        tech_data = tech_map.get(code)
        if tech_data is None:
            continue
        
        t30, t240, df30 = tech_data
        
        # Get news data
        raw_news = news_map.get(jp_name, {})
        news = normalize_news(jp_name, raw_news)
        
        # Analyze this symbol
        row = analyze_symbol(code, price, t30, t240, news)
        rows.append(row)
    
    return rows
