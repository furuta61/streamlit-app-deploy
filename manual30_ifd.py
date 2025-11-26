# -*- coding: utf-8 -*-
"""
30分 IFD 自動生成ロジック（あなた専用の実運用ロジック）
"""

from datetime import datetime


def generate_ifd(symbol: str, direction: str, entry_price: float, signal: str):
    """
    30分IFDの本番ロジック。
    Vision解析とTV方向をもとに IFD を生成する。
    """

    # --- 価格帯 ---
    entry = round(float(entry_price), 1)

    # --- 利確幅（銘柄別最適化） ---
    TP_MAP = {
        "GER40": 19,
        "JP225": 45,
        "NAS100": 28,
        "XAUUSD": 1.8,
    }

    # --- 損切り幅（固定） ---
    SL_MAP = {
        "GER40": -19,
        "JP225": -45,
        "NAS100": -28,
        "XAUUSD": -1.8,
    }

    sym = symbol.upper()

    tp_gap = TP_MAP.get(sym, 20)
    sl_gap = SL_MAP.get(sym, -20)

    if direction == "buy":
        tp1 = entry + tp_gap
        sl = entry + sl_gap
    else:
        tp1 = entry - tp_gap
        sl = entry - sl_gap

    # --- ロット ---
    lots = 1 if signal == "GO" else 2

    # --- IFD JSON本体 ---
    ifd_json = {
        "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "trade_mode": "MANUAL_30M",
        "orders": [
            {
                "instrument": sym,
                "direction": direction,
                "decision": signal,
                "lots": lots,
                "entry_order": {
                    "type": "limit",
                    "price": entry
                },
                "ifd_legs": [
                    {
                        "name": "IFD-30M",
                        "oco": {
                            "take_profit": {"price": tp1},
                            "stop_loss": {"price": sl}
                        }
                    }
                ]
            }
        ]
    }

    return ifd_json
