"""
utils_ifd.py
表形式表示 ＆ メール用テキスト生成
"""


def print_ifd_table(ifd_json):
  """ターミナル用の表表示"""
  order = ifd_json["orders"][0]

  symbol = order["instrument"]
  direction_jp = "買い" if order["direction"] == "buy" else "売り"
  lots = order.get("lots", 1)
  signal = order.get("decision", "-")
  run_id = ifd_json.get("run_id", "-")

  entry = order["entry_order"]["price"]

  # TP, SL（必ず存在）
  tp = order["ifd_legs"][0]["oco"]["take_profit"]["price"]
  sl = order["ifd_legs"][0]["oco"]["stop_loss"]["price"]

  # TP2（4H専用）: トップレベル tp2_price 優先 → レッグ2 → 旧仕様(TP2キー)
  tp2 = ifd_json.get("tp2_price")
  if tp2 is None:
    try:
      legs = order.get("ifd_legs", [])
      if len(legs) > 1:
        tp2 = legs[1]["oco"]["take_profit"]["price"]
      else:
        tp2 = order["ifd_legs"][0]["oco"].get("take_profit", {}).get("TP2")
    except Exception:
      tp2 = None
  if tp2 is None:
    tp2 = "-"

  # trailing（4H専用）
  trailing = ifd_json.get("trailing", None)
  trailing_text = (
    f"{trailing}" if trailing else "-"
  )

  print("\n================= IFD 注文（表） =================")
  print(f"run_id　　 : {run_id}")
  print(f"銘柄　　　 : {symbol}")
  print(f"方向　　　 : {direction_jp}")
  print(f"ロット数　 : {lots}")
  print(f"シグナル　 : {signal}")
  print(f"エントリー : {entry}")
  print(f"TP　　　　: {tp}")
  print(f"TP2　　　 : {tp2}")
  print(f"SL　　　　: {sl}")
  print(f"trailing　: {trailing_text}")
  print("=================================================\n")


def format_ifd_table_text(ifd_json):
  """メール本文用のテキスト表"""
  order = ifd_json["orders"][0]

  symbol = order["instrument"]
  direction_jp = "買い" if order["direction"] == "buy" else "売り"
  lots = order.get("lots", 1)
  signal = order.get("decision", "-")
  run_id = ifd_json.get("run_id", "-")

  entry = order["entry_order"]["price"]

  tp = order["ifd_legs"][0]["oco"]["take_profit"]["price"]
  sl = order["ifd_legs"][0]["oco"]["stop_loss"]["price"]

  # TP2（4H専用）: トップレベル→レッグ2→旧仕様
  tp2 = ifd_json.get("tp2_price")
  if tp2 is None:
    try:
      legs = order.get("ifd_legs", [])
      if len(legs) > 1:
        tp2 = legs[1]["oco"]["take_profit"]["price"]
      else:
        tp2 = order["ifd_legs"][0]["oco"].get("take_profit", {}).get("TP2")
    except Exception:
      tp2 = None
  if tp2 is None:
    tp2 = "-"

  # trailing
  trailing = ifd_json.get("trailing", None)
  trailing_text = f"{trailing}" if trailing else "-"

  text = ""
  text += "================ IFD 注文 ================\n"
  text += f"run_id　　 : {run_id}\n"
  text += f"銘柄　　　 : {symbol}\n"
  text += f"方向　　　 : {direction_jp}\n"
  text += f"ロット数　 : {lots}\n"
  text += f"シグナル　 : {signal}\n"
  text += f"エントリー : {entry}\n"
  text += f"TP　　　　: {tp}\n"
  text += f"TP2　　　 : {tp2}\n"
  text += f"SL　　　　: {sl}\n"
  text += f"trailing　: {trailing_text}\n"
  text += "==========================================\n"

  return text
