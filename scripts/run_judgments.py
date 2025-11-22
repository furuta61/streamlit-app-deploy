from app.mygpt_strategy import analyze_signal, generate_ifd
from app.config import TH
from datetime import datetime, timezone
import json

rows = [
    {
        "trade_mode": "DAY6H",
        "symbol": "JP225",
        "direction": "none",
        "entry_price": 50139.5,
        "SL": 48639.5,
        "TP1": 50839.5,
        "TP2": 51139.5,
        "order_type": "指値",
        "判定": "WAIT",
        "ニュースロック": False,
        "推奨度": "★★☆☆☆",
        "ロット": 0,
        "CUT_condition": "SMA25<SMA75 or MACD<Signal",
    },
    {
        "trade_mode": "DAY6H",
        "symbol": "NQ100",
        "direction": "none",
        "entry_price": 24760.8,
        "SL": 23260.8,
        "TP1": 25460.8,
        "TP2": 25760.8,
        "order_type": "指値",
        "判定": "WAIT",
        "ニュースロック": False,
        "推奨度": "★☆☆☆☆",
        "ロット": 0,
        "CUT_condition": "SMA25<SMA75 or MACD<Signal",
    },
    {
        "trade_mode": "DAY6H",
        "symbol": "XAUUSD",
        "direction": "none",
        "entry_price": 4068.1,
        "SL": 2568.1,
        "TP1": 4768.1,
        "TP2": 5068.1,
        "order_type": "指値",
        "判定": "WAIT",
        "ニュースロック": False,
        "推奨度": "★★☆☆☆",
        "ロット": 0,
        "CUT_condition": "SMA25>SMA75 or MACD<Signal",
    },
    {
        "trade_mode": "DAY6H",
        "symbol": "GER40",
        "direction": "none",
        "entry_price": 18125.4,
        "SL": 17925.4,
        "TP1": 18225.4,
        "TP2": 18325.4,
        "order_type": "指値",
        "判定": "WAIT",
        "ニュースロック": False,
        "推奨度": "★★☆☆☆",
        "ロット": 0,
        "CUT_condition": "SMA25<SMA75 or MACD<Signal",
    },
    {
        "trade_mode": "DAY6H",
        "symbol": "COPPER",
        "direction": "none",
        "entry_price": None,  # will be filled from yfinance
        "SL": None,
        "TP1": None,
        "TP2": None,
        "order_type": "指値",
        "判定": "WAIT",
        "ニュースロック": False,
        "推奨度": "★★☆☆☆",
        "ロット": 0,
        "CUT_condition": "SMA25<SMA75 or MACD<Signal",
    },
]

# Create synthetic screener values to reflect the CUT conditions
screener_map = {
    "JP225": {"source":"synthetic","symbol_used":"JP225","screener":"synthetic","exchange":"NA",
               "price": 50139.5, "SMA25": 50000.0, "SMA75": 51000.0, "RSI": 45.0, "MACD": -10.0, "MACD_signal": 0.0, "ATR": None, "Recommend": "NEUTRAL"},
    "NQ100": {"source":"synthetic","symbol_used":"NQ100","screener":"synthetic","exchange":"NA",
               "price": 24760.8, "SMA25": 24700.0, "SMA75": 25000.0, "RSI": 48.0, "MACD": -5.0, "MACD_signal": 0.0, "ATR": None, "Recommend": "NEUTRAL"},
    "XAUUSD": {"source":"synthetic","symbol_used":"XAUUSD","screener":"synthetic","exchange":"NA",
                "price": 4068.1, "SMA25": 4100.0, "SMA75": 4050.0, "RSI": 52.0, "MACD": 1.5, "MACD_signal": 0.5, "ATR": None, "Recommend": "NEUTRAL"},
}

# Try to fetch copper (HG=F) price via yfinance if available, otherwise default to 4.5
try:
    import yfinance as yf
    df = yf.download("HG=F", period="1d", interval="1h", progress=False)
    if df is not None and not df.empty:
        last_close = float(df['Close'].dropna().iloc[-1])
    else:
        last_close = 4.5
except Exception:
    last_close = 4.5

# update COPPER entry
for r in rows:
    if r['symbol'] == 'COPPER':
        r['entry_price'] = last_close
        r['SL'] = round(last_close * 0.95, 3)
        r['TP1'] = round(last_close * 1.05, 3)
        r['TP2'] = round(last_close * 1.08, 3)
        break

# add synthetic screener for GER40 and COPPER
scr_ger40 = {"source":"synthetic","symbol_used":"GER40","screener":"synthetic","exchange":"NA",
            "price": 18125.4, "SMA25": 17950.0, "SMA75": 18200.0, "RSI": 50.0, "MACD": -1.5, "MACD_signal": 0.0, "ATR": None, "Recommend": "NEUTRAL"}
scr_cu = {"source":"synthetic","symbol_used":"COPPER","screener":"synthetic","exchange":"NA",
          "price": last_close, "SMA25": last_close*0.99, "SMA75": last_close*1.01, "RSI": 48.0, "MACD": -0.2, "MACD_signal": 0.1, "ATR": None, "Recommend": "NEUTRAL"}

screener_map['GER40'] = scr_ger40
screener_map['COPPER'] = scr_cu

results = []
for r in rows:
    symbol = r["symbol"]
    payload = {"symbol": symbol, "price": r["entry_price"], "time": datetime.now(timezone.utc).isoformat()}
    screener = screener_map[symbol]
    out = analyze_signal(payload, 0.0, None, screener)
    rating = out["rating"]
    meta = out["meta"]
    if rating >= TH.strong_go:
        decision = "STRONG_GO"
    elif rating >= TH.go:
        decision = "GO"
    else:
        decision = "WAIT"

    ifd = generate_ifd(symbol, r["entry_price"], decision, rating, {**meta, "screener": screener})
    results.append({"symbol": symbol, "rating": round(float(rating), 3), "decision": decision, "ifd": ifd, "meta": meta})

print(json.dumps(results, ensure_ascii=False, indent=2))

# --- produce table in requested column order ---
from app.config import SYMBOL_SETTINGS, DEFAULT_DECIMALS

def get_setting(sym):
    s = SYMBOL_SETTINGS.get(sym)
    if s:
        return s
    return {"decimals": DEFAULT_DECIMALS, "tp1": 0.02, "tp2": 0.03, "sl": -0.01, "order_type": "LIMIT"}

rows_out = []
for r in results:
    sym = r['symbol']
    ifd = r['ifd']
    sett = get_setting(sym)
    d = sett['decimals']
    entry = round(float(ifd['entry_price']), d)
    sl = round(float(ifd['stop_loss']), d)
    tp1 = round(float(ifd['take_profit']), d)
    tp2 = round(entry * (1 + sett.get('tp2', 0.03)), d)
    rows_out.append({
        'trade_mode': 'DAY6H',
        '銘柄': sym,
        '方向': 'none',
        'entry_price': entry,
        'SL': sl,
        'TP1': tp1,
        'TP2': tp2,
        'order_type': sett.get('order_type','LIMIT'),
        '判定': r['decision'],
        'ニュースロック': 'false',
        '推奨度': '★' * max(1, min(5, int((r['rating']+6)//2))) ,
        'ロット': 0,
        'CUT条件': 'SMA25<SMA75 or MACD<Signal'
    })

import csv, sys
writer = csv.writer(sys.stdout)
writer.writerow(['trade_mode','銘柄','方向','entry_price','SL','TP1','TP2','order_type','判定','ニュースロック','推奨度','ロット','CUT条件'])
for row in rows_out:
    writer.writerow([row[k] for k in ['trade_mode','銘柄','方向','entry_price','SL','TP1','TP2','order_type','判定','ニュースロック','推奨度','ロット','CUT条件']])
