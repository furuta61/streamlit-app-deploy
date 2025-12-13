from __future__ import annotations
import json, os
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
import pandas as pd
import numpy as np
import yfinance as yf

from .config import PATH
from .market_data_sources import YF_TICKERS

def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)

def _hit_tp_sl(df: pd.DataFrame, entry_price: float, tp: float, sl: float, horizon_bars: int = 16) -> Tuple[str, float]:
    sub = df.iloc[:horizon_bars].copy()
    if sub.empty:
        return ("timeout", df["Close"].iloc[-1] if not df.empty else entry_price)
    for _, row in sub.iterrows():
        h = float(row["High"]); l = float(row["Low"])
        if h >= tp:  return ("TP", tp)
        if l <= sl:  return ("SL", sl)
    return ("timeout", float(sub["Close"].iloc[-1]))

def load_ifd(path: str | None = None) -> List[Dict[str, Any]]:
    p = path or PATH.ifd_output
    if not os.path.exists(p):
        print("⚠️ ifd_orders.jsonl が見つかりません。")
        return []
    out = []
    with open(p, "r") as f:
        for line in f:
            try:
                d = json.loads(line.strip())
                if d.get("decision") in ("GO","STRONG_GO"):
                    out.append(d)
            except Exception:
                pass
    return out

def run_backtest(horizon_bars: int = 16) -> Dict[str, Any]:
    trades = load_ifd()
    if not trades:
        print("⚠️ テスト対象の IFD がありません。先に運用でログを貯めてください。")
        return {}

    rows = []
    for t in trades:
        symbol = t["symbol"]
        yf_sym = YF_TICKERS.get(symbol)
        if not yf_sym:
            continue
        ts = _parse_ts(t["timestamp"])
        entry = float(t["entry_price"])
        tp = float(t["take_profit"])
        sl = float(t["stop_loss"])

        df = yf.download(yf_sym, period="2d", interval="30m", progress=False, auto_adjust=True)
        if df is None or df.empty:
            rows.append({**t, "exit_reason": "timeout", "profit": 0.0})
            continue
        df = df.tz_localize(None)
        df.index = pd.to_datetime(df.index, utc=True)
        future = df[df.index > ts]
        if future.empty:
            rows.append({**t, "exit_reason": "timeout", "profit": 0.0})
            continue

        reason, exit_price = _hit_tp_sl(future, entry, tp, sl, horizon_bars=horizon_bars)
        profit = (exit_price - entry) / entry
        rows.append({
            "timestamp": t["timestamp"], "symbol": symbol, "decision": t["decision"],
            "entry_price": entry, "tp": tp, "sl": sl,
            "exit_reason": reason, "exit_price": exit_price, "profit": profit
        })

    dfres = pd.DataFrame(rows)
    if dfres.empty:
        print("⚠️ 判定できる取引がありませんでした。")
        return {}

    total = len(dfres)
    win_rate = float((dfres["profit"] > 0).mean())
    avg_win = float(dfres.loc[dfres["profit"] > 0, "profit"].mean() or 0)
    avg_loss= float(dfres.loc[dfres["profit"] < 0, "profit"].mean() or 0)
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    dfres["cum"] = (1 + dfres["profit"]).cumprod()
    total_return = float(dfres["cum"].iloc[-1] - 1) if total>0 else 0
    rollmax = dfres["cum"].cummax()
    drawdown = (dfres["cum"] - rollmax) / rollmax
    max_dd = float(drawdown.min() if not drawdown.empty else 0)

    metrics = {
        "total_trades": total, "win_rate": win_rate, "profit_factor": profit_factor,
        "total_return": total_return, "max_drawdown": max_dd,
        "avg_win": avg_win, "avg_loss": avg_loss
    }

    os.makedirs("output/backtest", exist_ok=True)
    dfres.to_csv("output/backtest/backtest_trades.csv", index=False)
    with open("output/backtest/metrics.json","w") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print("=== Backtest ===")
    for k,v in metrics.items():
        print(f"{k}: {v:.4f}" if isinstance(v, float) else f"{k}: {v}")

    return metrics

if __name__ == "__main__":
    run_backtest()
