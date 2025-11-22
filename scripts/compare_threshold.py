#!/usr/bin/env python3
"""
既存 IFD ログを新旧閾値で再分類し、採用率とパフォーマンスの変化を調べる簡易比較。

- 現在のログ(output/ifd_orders.jsonl)は決定済み(GO/STRONG_GO/WAIT)を含む。
- 旧閾値(GO≥4.0, STRONG_GO≥6.0)でのフィルタ適用後 → バックテスト結果
- 新閾値(GO≥3.8, STRONG_GO≥5.5)でのフィルタ適用後 → バックテスト結果
- 結果をoutput/backtest/threshold_compare.mdとして出力。

注意: 既存ログにratingが無い場合は、決定が既に最終なのでフィルタし直す意味は薄い。
ただし、WAITも含むデータならば、新閾値で再評価してGOに格上げされるケースをシミュレートできる。
"""
import json, os, sys
from typing import List, Dict, Any

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.backtest import run_backtest
from app.config import PATH

IFD_SOURCE = "output/ifd_orders.jsonl"
OUT_DIR = "output/backtest"

OLD_GO = 4.0
OLD_STRONG = 6.0
NEW_GO = 3.8
NEW_STRONG = 5.5


def reclassify(ifd: Dict[str, Any], go_thresh: float, strong_thresh: float) -> str:
    """ratingがあれば閾値で再分類、無ければ元のdecisionを返す"""
    rating = ifd.get("rating")
    if rating is None:
        # ratingがないので元のdecisionを維持
        return ifd.get("decision", "WAIT")
    try:
        r = float(rating)
        if r >= strong_thresh:
            return "STRONG_GO"
        if r >= go_thresh:
            return "GO"
        return "WAIT"
    except Exception:
        return ifd.get("decision", "WAIT")


def filter_and_write(source: str, out_path: str, go_thresh: float, strong_thresh: float) -> int:
    """再分類してGO/STRONG_GOのみを新ファイルに書き出し、件数を返す"""
    if not os.path.exists(source):
        print(f"⚠️ Source not found: {source}")
        return 0
    count = 0
    with open(source, "r") as f_in, open(out_path, "w") as f_out:
        for line in f_in:
            try:
                d = json.loads(line.strip())
                dec = reclassify(d, go_thresh, strong_thresh)
                if dec in ("GO", "STRONG_GO"):
                    d["decision"] = dec  # override
                    f_out.write(json.dumps(d, ensure_ascii=False) + "\n")
                    count += 1
            except Exception:
                continue
    return count


def backtest_file(ifd_path: str) -> Dict[str, Any]:
    """指定IFDファイルをapp/backtestでテストし、メトリクスを返す"""
    # 一時的にPATH.ifd_outputを差し替える必要があるが、今回はシンプルにrun_backtest内でファイルを指定できないため、
    # 独自に簡易バックテストする or モジュールのパスを書き換える。
    # ここでは、app.backtest.load_ifd()を直接呼び出すために関数を複製します。
    import importlib
    import app.backtest as BT
    old_path = BT.PATH.ifd_output
    BT.PATH.ifd_output = ifd_path
    metrics = BT.run_backtest()
    BT.PATH.ifd_output = old_path
    return metrics


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # 旧閾値
    old_path = os.path.join(OUT_DIR, "ifd_filtered_old.jsonl")
    old_count = filter_and_write(IFD_SOURCE, old_path, OLD_GO, OLD_STRONG)
    print(f"Old threshold: {old_count} trades -> {old_path}")
    old_metrics = backtest_file(old_path) if old_count > 0 else {}

    # 新閾値
    new_path = os.path.join(OUT_DIR, "ifd_filtered_new.jsonl")
    new_count = filter_and_write(IFD_SOURCE, new_path, NEW_GO, NEW_STRONG)
    print(f"New threshold: {new_count} trades -> {new_path}")
    new_metrics = backtest_file(new_path) if new_count > 0 else {}

    # レポート生成
    report = f"""# Threshold Comparison Report

## Configuration

- **Old**: GO ≥ {OLD_GO}, STRONG_GO ≥ {OLD_STRONG}
- **New**: GO ≥ {NEW_GO}, STRONG_GO ≥ {NEW_STRONG}

## Results

| Metric         | Old         | New         | Change  |
|----------------|-------------|-------------|---------|
| Trades         | {old_count} | {new_count} | {new_count - old_count:+d} |
| Win Rate       | {old_metrics.get('win_rate',0):.4f} | {new_metrics.get('win_rate',0):.4f} | {new_metrics.get('win_rate',0) - old_metrics.get('win_rate',0):+.4f} |
| Profit Factor  | {old_metrics.get('profit_factor',0):.4f} | {new_metrics.get('profit_factor',0):.4f} | {new_metrics.get('profit_factor',0) - old_metrics.get('profit_factor',0):+.4f} |
| Total Return   | {old_metrics.get('total_return',0):.4f} | {new_metrics.get('total_return',0):.4f} | {new_metrics.get('total_return',0) - old_metrics.get('total_return',0):+.4f} |
| Max Drawdown   | {old_metrics.get('max_drawdown',0):.4f} | {new_metrics.get('max_drawdown',0):.4f} | {new_metrics.get('max_drawdown',0) - old_metrics.get('max_drawdown',0):+.4f} |
| Avg Win        | {old_metrics.get('avg_win',0):.4f} | {new_metrics.get('avg_win',0):.4f} | {new_metrics.get('avg_win',0) - old_metrics.get('avg_win',0):+.4f} |
| Avg Loss       | {old_metrics.get('avg_loss',0):.4f} | {new_metrics.get('avg_loss',0):.4f} | {new_metrics.get('avg_loss',0) - old_metrics.get('avg_loss',0):+.4f} |

## Summary

"""
    if new_count > old_count:
        report += f"- New threshold admits **{new_count - old_count} more trades** than old.\n"
    else:
        report += f"- New threshold admits **{old_count - new_count} fewer trades** than old.\n"

    if new_metrics.get("win_rate", 0) > old_metrics.get("win_rate", 0):
        report += "- New threshold shows **improved win rate**.\n"
    else:
        report += "- Win rate did not improve.\n"

    if new_metrics.get("profit_factor", 0) > old_metrics.get("profit_factor", 0):
        report += "- Profit factor is **better** under new threshold.\n"
    else:
        report += "- Profit factor is not improved.\n"

    report_path = os.path.join(OUT_DIR, "threshold_compare.md")
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\n✅ Report saved to {report_path}")

    # Also save JSON
    json_path = os.path.join(OUT_DIR, "threshold_compare.json")
    with open(json_path, "w") as f:
        json.dump({
            "old": {"count": old_count, "metrics": old_metrics},
            "new": {"count": new_count, "metrics": new_metrics},
        }, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON saved to {json_path}")


if __name__ == "__main__":
    main()
