#!/usr/bin/env python3
from datetime import datetime
from app.mygpt_screener import get_screener_auto

SYMS = ["JP225", "NQ100", "XAUUSD", "GER40"]

def main():
    print("=== get_screener_auto 統合テスト ===")
    print("実行時刻 (UTC):", datetime.utcnow().isoformat(), "\n")

    for sym in SYMS:
        scr = get_screener_auto(sym, "30m")
        print(f"[{sym}]")
        if scr is None:
            print("  ❌ screener: None（どのデータソースでも取得できず）")
        else:
            print(f"  source    : {scr.get('source')}")
            print(f"  symbol    : {scr.get('symbol_used')}")
            print(f"  price     : {scr.get('price')}")
            print(f"  SMA25/SMA75: {scr.get('SMA25')} / {scr.get('SMA75')}")
            print(f"  RSI       : {scr.get('RSI')}")
            print(f"  MACD/sig  : {scr.get('MACD')} / {scr.get('MACD_signal')}")
            print(f"  fetched_at: {scr.get('fetched_at')}")
        print("-" * 50)

if __name__ == "__main__":
    main()
