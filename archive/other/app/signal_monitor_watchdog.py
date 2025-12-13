from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from typing import Dict, Any
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

from .config import PATH, TH, LOGGER
from .duplicate_guard import has_been_processed, mark_processed
from .market_data_sources import get_screener_auto
from .mygpt_strategy import analyze_signal, generate_ifd
from .signal_monitor import _send_mail, _classify_decision, _write_ifd

class TradingViewLogHandler(FileSystemEventHandler):
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.last_pos = os.path.getsize(self.path) if os.path.exists(self.path) else 0

    def on_modified(self, event):
        if not isinstance(event, FileModifiedEvent):
            return
        if os.path.abspath(event.src_path) != self.path:
            return

        try:
            with open(self.path, "r") as f:
                f.seek(self.last_pos)
                new_lines = f.read().splitlines()
                self.last_pos = f.tell()
        except Exception as e:
            LOGGER.error(f"read error: {e}")
            return

        for raw in new_lines:
            self._process_line(raw)

    def _process_line(self, raw: str):
        try:
            rec = json.loads(raw)
        except Exception:
            return
        data = rec.get("data", {})
        symbol = data.get("symbol")
        price = float(data.get("price")) if data.get("price") else None
        ts = data.get("time") or rec.get("timestamp")
        signal = data.get("signal")

        if not symbol or not ts:
            return

        if has_been_processed(symbol, ts, price, signal):
            LOGGER.warning(f"⚠️ Skipped duplicate {symbol} @{ts}")
            return

        screener = get_screener_auto(symbol)
        if screener:
            LOGGER.info(f"📊 Screener for {symbol}: src={screener.get('source')} used={screener.get('symbol_used')} ATR={screener.get('ATR')}")
        else:
            LOGGER.warning(f"⚠️ Screener not available for {symbol}")

        news_score = 1.5
        out = analyze_signal(data, news_score, None, screener)
        rating = out["rating"]
        meta = out["meta"] | ({"screener": screener} if screener else {})
        decision = _classify_decision(rating)

        # screener が先物ティッカーを返す場合は screener.price を entry に使わない
        sc = screener or {}
        sc_sym = str(sc.get("symbol_used", ""))
        screener_price = None
        if sc and sc.get("price") is not None:
            if sc_sym.endswith("=F") or sc_sym in {"SI=F","GC=F","NG=F","CL=F","HG=F"}:
                LOGGER.warning(f"⚠️ Ignoring screener.price for futures ticker {sc_sym}")
                screener_price = None
            else:
                screener_price = sc.get("price")

        entry = price if price is not None else screener_price
        if not entry:
            mark_processed(symbol, ts, price, signal)
            return

        ifd = generate_ifd(symbol, entry, decision, rating, meta)
        # persist incoming raw payload for traceability
        line = {"timestamp": datetime.now(timezone.utc).isoformat(), "incoming_payload": data, **ifd}
        _write_ifd(line)

        subject = f"🚨 {decision} - {symbol}"
        body = f"{symbol} @{entry}\nRating: {rating:.2f}\nTP: {ifd['take_profit']} / SL: {ifd['stop_loss']}\n"
        _send_mail(subject, body)

        mark_processed(symbol, ts, price, signal)

def main_loop_watchdog():
    LOGGER.info("🚀 Monitoring with Watchdog ...")
    os.makedirs(os.path.dirname(PATH.tradingview_log), exist_ok=True)
    handler = TradingViewLogHandler(PATH.tradingview_log)
    observer = Observer()
    observer.schedule(handler, path=os.path.dirname(PATH.tradingview_log) or ".", recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    LOGGER.info("👋 Stopped.")

if __name__ == "__main__":
    main_loop_watchdog()
