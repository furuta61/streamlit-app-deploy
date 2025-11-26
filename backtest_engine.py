# backtest_engine.py
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
BACKTEST_FILE = BASE_DIR / "output" / "backtest_results.json"
BACKTEST_FILE.parent.mkdir(exist_ok=True, parents=True)

def record_trade(symbol, direction, entry, tp, sl, result):
    """
    トレード結果をJSONに保存
    result: "win" / "loss" / "breakeven"
    """
    data = {
        "symbol": symbol,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "direction": direction,
        "entry": entry,
        "tp": tp,
        "sl": sl,
        "result": result
    }

    trades = []
    if BACKTEST_FILE.exists():
        trades = json.load(open(BACKTEST_FILE, "r", encoding="utf-8"))

    trades.append(data)
    if len(trades) > 200:
        trades = trades[-200:]  # 最新200件だけ保持

    json.dump(trades, open(BACKTEST_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


def get_win_rate(symbol):
    """
    過去30件の勝率を返す
    """
    if not BACKTEST_FILE.exists():
        return 0.5

    trades = json.load(open(BACKTEST_FILE, "r", encoding="utf-8"))
    trades = [t for t in trades if t["symbol"] == symbol][-30:]
    if not trades:
        return 0.5

    wins = sum(1 for t in trades if t["result"] == "win")
    return round(wins / len(trades), 2)
