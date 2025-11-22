# -*- coding: utf-8 -*-
"""
manual30_ifd.py
30分 手動IFD生成ツール
STRONG_GO: +1500円（1口）
GO: +700円（1口）

使い方:
  - 対話モード: 引数なしで実行し、プロンプトに従って入力
  - CLIモード: --symbol --direction --entry --signal を指定
      例)
        python manual30_ifd.py \
          --symbol GER40 --direction sell --entry 23762 --signal STRONG_GO --save

備考:
  - 目標利確は「JPY/口」を各銘柄の point_value (1ポイントあたりのJPY/口)で割って価格差に換算
  - SLはTP距離と同じ幅（調整可）
  - 価格の丸めは簡易ルール（JP225/GER40: 0桁, NAS100: 1桁, XAUUSD: 2桁）
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict
from utils_ifd import print_ifd_table

# 1ポイントあたりのJPY/口（暫定値。ブローカー仕様に合わせ要調整）
POINT_VALUE_MAP: Dict[str, float] = {
    "JP225": 100.0,
    "NAS100": 20.0,
    "GER40": 80.0,
    # XAUUSD はUSD変動をJPYに換算が本来必要。暫定で150JPY/口/point相当。
    "XAUUSD": 150.0,
}

# 簡易の小数桁ルール
DECIMALS_MAP: Dict[str, int] = {
    "JP225": 0,
    "GER40": 0,
    "NAS100": 1,
    "XAUUSD": 2,
}


def round_price(symbol: str, price: float) -> float:
    d = DECIMALS_MAP.get(symbol.upper(), 1)
    return round(float(price), d)


def jpy_to_price_delta(symbol: str, jpy_per_lot: float) -> float:
    pv = float(POINT_VALUE_MAP.get(symbol.upper(), 1.0))
    try:
        return float(jpy_per_lot) / pv if pv > 0 else float(jpy_per_lot)
    except Exception:
        return float(jpy_per_lot)


def generate_ifd(symbol: str, direction: str, entry: float, signal: str):
    symbol = symbol.upper().strip()
    direction = direction.lower().strip()
    signal = signal.upper().strip()

    if signal == "STRONG_GO":
        tp_jpy = 1500.0
        lots = 1
    elif signal == "GO":
        tp_jpy = 700.0
        lots = 1
    else:
        raise ValueError("signal は GO または STRONG_GO のみ")

    # JPY/口 → 価格差（ポイント）
    tp_distance = jpy_to_price_delta(symbol, tp_jpy)
    sl_distance = tp_distance  # 同距離。必要なら比率変更可。

    if direction not in ("buy", "sell"):
        raise ValueError("direction は buy / sell のみ")

    entry = float(entry)

    if direction == "buy":
        tp_price = entry + tp_distance
        sl_price = entry - sl_distance
    else:
        tp_price = entry - tp_distance
        sl_price = entry + sl_distance

    # 丸め
    entry_r = round_price(symbol, entry)
    tp_r = round_price(symbol, tp_price)
    sl_r = round_price(symbol, sl_price)

    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    ifd = {
        "run_id": run_id,
        "trade_mode": "MANUAL_30M",
        "orders": [
            {
                "instrument": symbol,
                "direction": direction,
                "decision": signal,
                "lots": int(lots),
                "entry_order": {
                    "type": "limit",
                    "price": entry_r,
                },
                "ifd_legs": [
                    {
                        "name": "IFD-30M",
                        "oco": {
                            "take_profit": {"price": tp_r},
                            "stop_loss": {"price": sl_r},
                        },
                    }
                ],
            }
        ],
    }
    return ifd




def main():
    p = argparse.ArgumentParser(description="30分 手動IFD生成ツール (JPY/口ターゲット方式)")
    p.add_argument("--symbol", type=str, help="銘柄 (JP225/NAS100/XAUUSD/GER40)")
    p.add_argument("--direction", type=str, help="buy/sell")
    p.add_argument("--entry", type=float, help="エントリー価格")
    p.add_argument("--signal", type=str, help="GO または STRONG_GO")
    p.add_argument("--save", action="store_true", help="output/ に JSON を保存")
    args = p.parse_args()

    if args.symbol and args.direction and args.entry is not None and args.signal:
        obj = generate_ifd(args.symbol, args.direction, args.entry, args.signal)
    else:
        print("=== 30分手動IFD ジェネレーター (対話モード) ===")
        symbol = input("銘柄（例 JP225, NAS100, GER40, XAUUSD）: ").strip()
        direction = input("方向（buy / sell）: ").strip()
        entry = float(input("エントリー価格: ").strip())
        signal = input("シグナル（GO / STRONG_GO）: ").strip()
        obj = generate_ifd(symbol, direction, entry, signal)

    print("\n=== 生成された IFD ===")
    print(json.dumps(obj, indent=2, ensure_ascii=False))

    # 表形式での出力
    print_ifd_table(obj)

    if getattr(args, "save", False):
        out_dir = Path(__file__).resolve().parent / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_fp = out_dir / f"ifd_manual30_{obj['run_id']}.json"
        with open(out_fp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        print(f"\nSaved: {out_fp}")


if __name__ == "__main__":
    main()
