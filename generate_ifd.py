#!/usr/bin/env python3
import json
import os
from datetime import datetime
import glob
import pandas as pd

CONFIG = {
    # provisional TP values (points) used for proposal generation only — verify against broker specs
    "TP": {
        "JP225": 700,
        "NAS100": 100,
        "XAUUSD": 15,
        "US30": 500,
        "COPPER": 0.15
    },
    "TP_STRONG": {
        "JP225": 1000,
        "NAS100": 150,
        "XAUUSD": 20,
        "US30": 800,
        "COPPER": 0.25
    },
    "LOTS": {"GO": 4, "STRONG_GO": 6},
}

# provisional mapping: how many JPY per 1 point move for 1 lot. VERIFY with broker specs before live.
POINT_VALUE_MAP = {
    'JP225': 100,   # 1 point ~ 100 JPY per lot (provisional)
    'NAS100': 20,
    'US30': 100,
    'XAUUSD': 150,
    'COPPER': 1000,
}

# target JPY per lot for TP depending on strength
DESIRED_JPY_PER_LOT = {
    'STRONG_GO': 2000,
    'GO': 1000,
}

# number of decimal places to keep per instrument (to avoid integer rounding for small-decimal instruments)
DECIMALS = {
    'JP225': 0,
    'NAS100': 0,
    'US30': 0,
    'XAUUSD': 2,
    'COPPER': 3,
}

# ENTRY adjustment fractions are configurable via env vars for rapid tuning.
# These defaults are more aggressive than previous behavior to improve fill probability.
ENTRY_ADJ_ATR_FRAC = float(os.getenv('ENTRY_ADJ_ATR_FRAC', '0.5'))  # fraction of ATR to consider
ENTRY_ADJ_TP_FRAC = float(os.getenv('ENTRY_ADJ_TP_FRAC', '0.75'))  # fraction of TP points to consider

# Quiet hours (local time) during which aggressive entries are disabled by default.
# Default: disable aggressive behavior from 00:00 to 07:30 local time (user sleeps).
QUIET_START_HOUR = float(os.getenv('QUIET_START_HOUR', '0.0'))
QUIET_END_HOUR = float(os.getenv('QUIET_END_HOUR', '7.5'))


def load_entry_results(path="./output/entry_result.json"):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_atr_from_csv(symbol):
    # try to find any *_241.csv in ./data/<symbol>/
    pattern = os.path.join("./data", symbol, "*_241.csv")
    files = glob.glob(pattern)
    if not files:
        return None
    # read last file
    df = pd.read_csv(files[-1], index_col=0, parse_dates=True)
    # ensure high/low/close exist
    if not all(c in df.columns for c in ("High", "Low", "Close")):
        return None
    high = df['High']
    low = df['Low']
    close = df['Close']
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False).mean()
    return float(atr.iloc[-1])


def build_ifd(order):
    # order is a dict from entry_result; expected keys: instrument, decision, close_30, atr_4h (optional)
    sym = order.get('instrument')
    decision = order.get('decision')
    if decision is None or sym is None:
        return None
    if decision == 'WAIT':
        return None

    # entry price: prefer close_30 then close_4h
    entry = order.get('close_30') or order.get('close_4h')
    if entry is None:
        return None

    # ATR: prefer provided atr_4h, else compute from CSV, else fallback to sensible default
    atr = order.get('atr_4h')
    if atr is None:
        atr = compute_atr_from_csv(sym)
    if atr is None:
        # fallback values (conservative)
        atr = 100 if sym == 'JP225' else (50 if sym == 'NAS100' else 10)

    lots = CONFIG['LOTS']['STRONG_GO' if decision == 'STRONG_GO' else 'GO']
    sl_base = atr * 2

    # determine decimals for this instrument
    decimals = DECIMALS.get(sym, 0)

    # compute tp delta in points aiming for desired JPY per lot when possible
    desired_jpy = DESIRED_JPY_PER_LOT['STRONG_GO' if decision == 'STRONG_GO' else 'GO']
    pv = POINT_VALUE_MAP.get(sym)
    if pv:
        # desired points = desired_jpy / JPY per point
        tp_points = float(desired_jpy) / float(pv)
    else:
        # fallback to config values (legacy behaviour)
        tp_points = CONFIG['TP_STRONG'].get(sym) if decision == 'STRONG_GO' else CONFIG['TP'].get(sym)

    # ensure tp_points is positive and reasonable
    try:
        tp_points = max(0.0001, float(tp_points))
    except Exception:
        tp_points = 1.0

    # --- Aggressive entry adjustment for STRONG_GO ---
    # When STRONG_GO, nudge the entry price toward the market to increase fill probability.
    # Compute an offset as the smaller of (25% ATR) and (50% of TP points), then move the
    # entry toward the TP direction: for longs move entry down, for shorts move entry up.
    entry_adj = float(entry)
    if decision == 'STRONG_GO':
        # determine local hour (system local time)
        try:
            from datetime import datetime as _dt
            local_hour = (_dt.now()).hour + (_dt.now()).minute / 60.0
        except Exception:
            local_hour = None

        # if within quiet hours, skip aggressive adjustment
        in_quiet = False
        try:
            if local_hour is not None:
                if QUIET_START_HOUR <= QUIET_END_HOUR:
                    in_quiet = (local_hour >= QUIET_START_HOUR and local_hour < QUIET_END_HOUR)
                else:
                    # wrap-around (e.g., QUIET_START=22, QUIET_END=7)
                    in_quiet = not (local_hour >= QUIET_END_HOUR and local_hour < QUIET_START_HOUR)
        except Exception:
            in_quiet = False

        if not in_quiet:
            try:
                adj_from_atr = abs(float(atr)) * ENTRY_ADJ_ATR_FRAC
            except Exception:
                adj_from_atr = float(tp_points) * (ENTRY_ADJ_TP_FRAC * 0.5)
            adj_from_tp = abs(float(tp_points)) * ENTRY_ADJ_TP_FRAC
            entry_offset = min(adj_from_atr, adj_from_tp)

            # For instruments where TP is below entry we treat as short (XAUUSD/GOLD)
            is_short_like = sym in ('XAUUSD', 'GOLD')
            if is_short_like:
                # move entry up to be easier to short
                entry_adj = float(entry) + entry_offset
            else:
                # move entry down to be easier to long
                entry_adj = float(entry) - entry_offset
        else:
            # in quiet hours: no aggressive adjustment
            entry_adj = float(entry)

    # use entry_adj for subsequent calculations
    entry_used = entry_adj

    # rounding formatter per instrument
    def fmt_price(val):
        if decimals == 0:
            return int(round(val))
        else:
            return round(float(val), decimals)

    if sym == 'JP225':
        tp1 = fmt_price(entry_used + tp_points)
        tp2 = fmt_price(entry_used + tp_points + 200)
        sl = fmt_price(entry_used - sl_base)
    elif sym == 'NAS100' or sym == 'NASDAQ':
        tp1 = fmt_price(entry_used + tp_points)
        tp2 = fmt_price(entry_used + tp_points + 50)
        sl = fmt_price(entry_used - sl_base)
    elif sym == 'US30' or sym == 'US':
        tp1 = fmt_price(entry_used + tp_points)
        tp2 = fmt_price(entry_used + tp_points + 150)
        sl = fmt_price(entry_used - sl_base)
    elif sym == 'XAUUSD' or sym == 'GOLD':
        # user-specified sample uses TP below entry (assumes short)
        tp1 = fmt_price(entry_used - tp_points)
        tp2 = fmt_price(entry_used - tp_points - 5)
        sl = fmt_price(entry_used + sl_base)
    elif sym == 'COPPER':
        # COPPER quoted in small decimals; assume long-based TP
        tp1 = fmt_price(entry_used + tp_points)
        # add a small second leg margin for COPPER
        tp2 = fmt_price(entry_used + tp_points + 0.05)
        sl = fmt_price(entry_used - sl_base)
    else:
        return None

    entry_price_formatted = int(round(entry_used)) if decimals == 0 else round(float(entry_used), decimals)

    return {
        'instrument': sym,
        'decision': decision,
        'lots': lots,
        'entry_price': entry_price_formatted,
        'ifd_legs': [
            {'name': 'IFD-1', 'oco': {'take_profit': {'price': tp1}, 'stop_loss': {'price': sl}}},
            {'name': 'IFD-2', 'oco': {'take_profit': {'price': tp2}, 'stop_loss': {'price': sl},
                                      'trailing_stop': {'activate_after': tp2, 'distance': 300}}}
        ]
    }


def main():
    data = load_entry_results()
    if not data:
        print('❌ entry_result.json が見つかりません。 ./output/entry_result.json を確認してください')
        return

    # support both 'orders' and 'results' keys
    items = data.get('orders') or data.get('results') or []

    ifd_orders = []
    for o in items:
        ifd = build_ifd(o)
        if ifd:
            ifd_orders.append(ifd)

    result_json = {
        'run_id': datetime.utcnow().strftime('%Y%m%dT%H%M%SZ'),
        'orders': ifd_orders
    }

    os.makedirs('./output', exist_ok=True)
    json_path = './output/ifd_proposals.json'
    md_path = './output/ifd_proposals.md'

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, indent=2, ensure_ascii=False)

    # Markdown
    lines = ['| 銘柄 | 判定 | entry | TP1 | TP2 | SL | ロット | 判定強度 |', '|---|---:|---:|---:|---:|---:|---:|---:']
    for o in ifd_orders:
        i1 = o['ifd_legs'][0]['oco']
        i2 = o['ifd_legs'][1]['oco']
        strength = '★' * (3 if o['lots'] == 4 else 5)  # rough
        lines.append(f"| {o['instrument']} | {o['decision']} | {o['entry_price']} | {i1['take_profit']['price']} | {i2['take_profit']['price']} | {i1['stop_loss']['price']} | {o['lots']} | {strength} |")

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"✅ IFD提案を生成しました: {json_path}, {md_path}")


if __name__ == '__main__':
    main()
