# -*- coding: utf-8 -*-
"""
IFDOCO注文JSON構築モジュール
"""
from datetime import datetime

def build_ifdoco(symbol: str, direction: str, entry: float, tp: float, sl: float):
    return {
        "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "trade_mode": "DAYTRADE_IFDOCO",
        "orders": [
            {
                "instrument": symbol,
                "direction": direction,
                "entry_order": {"type": "limit", "price": entry},
                "ifd_legs": [
                    {
                        "oco": {
                            "take_profit": {"price": tp},
                            "stop_loss": {"price": sl}
                        }
                    }
                ]
            }
        ]
    }
