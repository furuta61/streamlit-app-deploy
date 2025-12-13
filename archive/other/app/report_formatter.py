from __future__ import annotations
from typing import List, Dict, Any

# Copilot: すべてのシグナル出力は、下記の13列だけを持つ Markdown 表に整形すること。
# 列順: trade_mode, 銘柄, 方向, entry_price, SL, TP1, TP2, order_type,
#       判定, ニュースロック, 推奨度, ロット, CUT条件
# 値が無いときは '–' を出力する。

# この列順・項目名を「唯一の正」とする。
MARKET_TABLE_COLUMNS = [
    "trade_mode",
    "銘柄",
    "方向",
    "entry_price",
    "SL",
    "TP1",
    "TP2",
    "order_type",
    "判定",
    "ニュースロック",
    "推奨度",
    "ロット",
    "CUT条件",
]


def _cell(value: Any) -> str:
    """値が None や空のときは '–' を入れる。Markdown 用に文字列に変換。"""
    if value is None:
        return "–"
    if isinstance(value, str) and not value.strip():
        return "–"
    return str(value)


def format_orders_as_markdown_table(orders: List[Dict[str, Any]]) -> str:
    """
    IFD提案やシグナル結果を、決まった形の Markdown 表に整形する。

    列は次の13列で固定する：
      trade_mode, 銘柄, 方向, entry_price, SL, TP1, TP2,
      order_type, 判定, ニュースロック, 推奨度, ロット, CUT条件

    orders の各要素は上記キーを持つ dict を想定。
    足りないキーは '–' で埋める。
    """
    header = "| " + " | ".join(MARKET_TABLE_COLUMNS) + " |"
    separator = "| " + " | ".join("---" for _ in MARKET_TABLE_COLUMNS) + " |"

    rows = [header, separator]

    for o in orders:
        row_cells = [_cell(o.get(col)) for col in MARKET_TABLE_COLUMNS]
        row = "| " + " | ".join(row_cells) + " |"
        rows.append(row)

    return "\n".join(rows)


if __name__ == "__main__":
    # Copilot に「お手本」を見せるためのサンプル
    sample_orders = [
        {
            "trade_mode": "DAY6H",
            "銘柄": "JP225",
            "方向": "–",
            "entry_price": "–",
            "SL": "–",
            "TP1": "–",
            "TP2": "–",
            "order_type": "–",
            "判定": "WAIT",
            "ニュースロック": "false",
            "推奨度": "★★☆☆☆",
            "ロット": 0,
            "CUT条件": "SMA25<SMA75 or MACD<Signal",
        }
    ]
    print(format_orders_as_markdown_table(sample_orders))
