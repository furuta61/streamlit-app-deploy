#!/usr/bin/env python3
"""
AB Backtest from TradingView log
- Replays output/tradingview.jsonl
- Runs analyze_signal under two scenarios (old/new) with news disabled for determinism
- Generates IFDs into separate files
- Runs an internal backtest per file using yfinance (30m)
- Writes summary metrics side-by-side to output/backtest/ab_metrics.json

Note:
- To avoid network-dependent news variance, this script injects news_items=[] and sentiment_score=0.0.
- Screener data is not replayed (not in tv log), so RSI/Recommend adjustments won't apply.
- Extreme-move bonus requires change_pct; absent in tv log, so it'll be effectively 0 in both scenarios.
"""
from __future__ import annotations
import os, json, sys, math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

import pandas as pd
import yfinance as yf

# Ensure project root is on sys.path for module imports
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Local imports
import mygpt_strategy as M
from app.market_data_sources import YF_TICKERS

TV_LOG = "output/tradingview.jsonl"
OUT_DIR = "output/backtest"

@dataclass
class Scenario:
    label: str
    env: Dict[str, str]

SCENARIOS = [
    Scenario(
        label="old",
        env={
            # Old: 旧閾値、エクストリームボーナス無し、tech=1.0でニュース不使用
            "TECH_WEIGHT": "1.0",
            "NEWS_WEIGHT": "0.0",
            "GO_THRESHOLD": "4.0",
            "STRONG_GO_THRESHOLD": "6.0",
            "EXTREME_MOVE_ON": "0",
        },
    ),
    Scenario(
        label="new",
        env={
            # New: 新閾値(低め)、エクストリームボーナスあり、tech=1.0でニュース不使用
            "TECH_WEIGHT": "1.0",
            "NEWS_WEIGHT": "0.0",
            "GO_THRESHOLD": "3.8",
            "STRONG_GO_THRESHOLD": "5.5",
            "EXTREME_MOVE_ON": "1",
        },
    ),
]


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
        h = float(row.get("High"))
        l = float(row.get("Low"))
        if h >= tp:
            return ("TP", tp)
        if l <= sl:
            return ("SL", sl)
    return ("timeout", float(sub["Close"].iloc[-1]))


def _load_tv_log(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        print(f"⚠️ tradingview log not found: {path}")
        return rows
    with open(path, "r") as f:
        for line in f:
            try:
                d = json.loads(line.strip())
                if not isinstance(d, dict):
                    continue
                payload = d.get("data") or {}
                if not payload:
                    continue
                rows.append(payload)
            except Exception:
                continue
    return rows


def _backtest_file(ifd_path: str, horizon_bars: int = 16) -> Dict[str, Any]:
    trades: List[Dict[str, Any]] = []
    if not os.path.exists(ifd_path):
        return {}
    with open(ifd_path, "r") as f:
        for line in f:
            try:
                d = json.loads(line.strip())
                if d.get("decision") in ("GO","STRONG_GO"):
                    trades.append(d)
            except Exception:
                pass
    if not trades:
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

        try:
            df = yf.download(yf_sym, period="2d", interval="30m", progress=False, auto_adjust=True)
        except Exception:
            df = None
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
        profit = (exit_price - entry) / entry if t.get("side","BUY") == "BUY" else (entry - exit_price) / entry
        rows.append({
            "timestamp": t["timestamp"], "symbol": symbol, "decision": t["decision"], "side": t.get("side","BUY"),
            "entry_price": entry, "tp": tp, "sl": sl,
            "exit_reason": reason, "exit_price": exit_price, "profit": profit
        })

    dfres = pd.DataFrame(rows)
    if dfres.empty:
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

    # Persist detailed trades
    label = os.path.splitext(os.path.basename(ifd_path))[0]
    os.makedirs(OUT_DIR, exist_ok=True)
    dfres.to_csv(os.path.join(OUT_DIR, f"{label}_trades.csv"), index=False)
    with open(os.path.join(OUT_DIR, f"{label}_metrics.json"), "w") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    return metrics


def run_scenario(tv_rows: List[Dict[str, Any]], sc: Scenario) -> Tuple[str, Dict[str, Any]]:
    # Apply env overrides for this process
    for k,v in sc.env.items():
        os.environ[k] = str(v)

    # Force module-level reload to pick up new env vars (TECH_WEIGHT, NEWS_WEIGHT, GO/STRONG_GO thresholds)
    # Because mygpt_strategy reads them at import time via _get_float_env
    import importlib
    importlib.reload(M)

    # Route generated IFDs to scenario-specific file by monkey-patching OUTPUT_PATH
    out_path = os.path.join(OUT_DIR, f"ifd_{sc.label}.jsonl")
    os.makedirs(OUT_DIR, exist_ok=True)
    try:
        os.remove(out_path)
    except FileNotFoundError:
        pass
    M.OUTPUT_PATH = out_path

    # Replay
    gen_count = 0
    for row in tv_rows:
        symbol = row.get("symbol")
        price = row.get("price")
        signal = row.get("signal")
        ts = row.get("time")
        if not symbol or price is None or not signal:
            continue
        payload = {
            **row,
            # inject deterministic news placeholders to avoid network calls
            "news_items": [],
            "sentiment_score": 0.0,
        }
        analysis = M.analyze_signal(symbol, payload)
        decision = analysis.get("decision")
        side = analysis.get("side") or "BUY"
        if decision in ("GO","STRONG_GO"):
            # skip unsupported symbols that lack TP_SL_RATES in mygpt_strategy
            if symbol not in M.TP_SL_RATES:
                continue
            # generate IFD with meta attached; entry is the tv price
            M.generate_ifd(symbol, float(price), decision, meta=analysis, side=side)
            gen_count += 1
    return out_path, {"generated": gen_count}


def main():
    tv_rows = _load_tv_log(TV_LOG)
    if not tv_rows:
        print("⚠️ No TradingView rows to replay. Aborting.")
        return 2

    results = {}
    for sc in SCENARIOS:
        print(f"\n=== Running scenario: {sc.label} ===")
        ifd_path, info = run_scenario(tv_rows, sc)
        print(f"generated orders: {info['generated']} -> {ifd_path}")
        metrics = _backtest_file(ifd_path)
        results[sc.label] = {
            "ifd_path": ifd_path,
            "generated": info["generated"],
            "metrics": metrics,
        }

    # write combined metrics
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "ab_metrics.json"), "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Print compact diff
    def fmt(m: Dict[str, Any], k: str) -> str:
        v = m.get(k)
        if v is None: return "-"
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)

    oldm = results.get("old",{}).get("metrics",{})
    newm = results.get("new",{}).get("metrics",{})
    print("\n=== A/B Summary ===")
    print(f"old: trades={fmt(oldm,'total_trades')}, win={fmt(oldm,'win_rate')}, PF={fmt(oldm,'profit_factor')}, ret={fmt(oldm,'total_return')}, DD={fmt(oldm,'max_drawdown')}")
    print(f"new: trades={fmt(newm,'total_trades')}, win={fmt(newm,'win_rate')}, PF={fmt(newm,'profit_factor')}, ret={fmt(newm,'total_return')}, DD={fmt(newm,'max_drawdown')}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
