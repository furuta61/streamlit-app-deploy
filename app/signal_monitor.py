from __future__ import annotations
import time, json, os, smtplib, ssl
from email.mime.text import MIMEText
from datetime import datetime, timezone
from typing import Dict, Any

from .config import PATH, EMAIL, TH, TV, LOGGER, REL
from .duplicate_guard import has_been_processed, mark_processed
from .market_data_sources import get_screener_auto
from .mygpt_strategy import analyze_signal, generate_ifd

SYMBOLS = ["JP225","NQ100","XAUUSD","XAGUSD","NGAS","GER40"]

def _send_mail(subject: str, body: str) -> bool:
    if not (EMAIL.from_addr and EMAIL.to_addr and EMAIL.app_password):
        LOGGER.info(f"[DryRun email] {subject}\n{body}")
        return True
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = EMAIL.from_addr
        msg["To"] = EMAIL.to_addr
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(EMAIL.smtp_host, EMAIL.smtp_port, context=context) as server:
            server.login(EMAIL.from_addr, EMAIL.app_password)
            server.send_message(msg)
        LOGGER.info(f"📨 Mail sent: {subject}")
        return True
    except Exception as e:
        LOGGER.error(f"❌ Mail send failed: {e}")
        return False

def _classify_decision(rating: float) -> str:
    if rating >= TH.strong_go: return "STRONG_GO"
    if rating >= TH.go: return "GO"
    return "WAIT"

def _iter_new_lines(path: str, last_size: int):
    cur_size = os.path.getsize(path)
    if cur_size == last_size:
        return last_size, []
    with open(path, "r") as f:
        if last_size > 0:
            f.seek(last_size)
        new_lines = f.read().splitlines()
    return cur_size, new_lines


def _parse_ts_to_epoch(ts: Any) -> float | None:
    """Try to parse timestamp field to epoch seconds. Returns None if cannot parse."""
    try:
        # numeric epoch
        if isinstance(ts, (int, float)):
            return float(ts)
        s = str(ts)
        # ISO8601
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(s)
            return dt.timestamp()
        except Exception:
            pass
        # plain numeric string
        return float(s)
    except Exception:
        return None


_suppression_store: dict[str, list[float]] = {}


def _load_suppression_cache():
    """Load suppression cache from disk into _suppression_store.
    Older timestamps outside the suppression window are pruned.
    """
    try:
        if not os.path.exists(PATH.suppression_cache):
            return
        with open(PATH.suppression_cache, 'r', encoding='utf-8') as f:
            data = json.load(f)
        now = time.time()
        for k, v in (data or {}).items():
            if not isinstance(v, list):
                continue
            # ensure numeric timestamps, prune old entries
            clean = []
            for t in v:
                try:
                    tt = float(t)
                except Exception:
                    continue
                if now - tt <= REL.suppression_window_sec:
                    clean.append(tt)
            if clean:
                _suppression_store[k] = clean
    except Exception as e:
        LOGGER.warning(f"failed loading suppression cache: {e}")

def _suppression_key(symbol: str, decision: str, entry: float | None) -> str:
    # Normalize entry price into short string
    entry_str = "NA"
    try:
        if entry is not None:
            e = float(entry)
            entry_str = f"{e:.4f}" if abs(e) < 100 else f"{e:.2f}"
    except Exception:
        entry_str = str(entry)
    return f"{symbol}::{decision}::{entry_str}"

def _prune_and_count(key: str, now_ts: float) -> int:
    lst = _suppression_store.get(key, [])
    window = REL.suppression_window_sec
    pruned = [t for t in lst if now_ts - t <= window]
    _suppression_store[key] = pruned
    return len(pruned)

def _record_suppression(key: str, now_ts: float):
    lst = _suppression_store.get(key, [])
    lst.append(now_ts)
    _suppression_store[key] = lst
    # persist minimal metrics
    try:
        import json
        os.makedirs(os.path.dirname(PATH.suppression_cache), exist_ok=True)
        with open(PATH.suppression_cache, 'w', encoding='utf-8') as f:
            json.dump({k: v[-10:] for k, v in _suppression_store.items()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        LOGGER.warning(f"suppression cache save error: {e}")

def _write_ifd(line: Dict[str, Any]):
    os.makedirs(os.path.dirname(PATH.ifd_output), exist_ok=True)
    with open(PATH.ifd_output, "a") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    # Log whether this IFD is intended for automatic execution or manual review
    try:
        mode = "AUTO" if bool(line.get("auto_execute")) else "MANUAL"
    except Exception:
        mode = "MANUAL"
    LOGGER.info(f"✅ IFD appended: {line['symbol']} {line.get('decision')} TP={line['take_profit']} SL={line['stop_loss']} mode={mode}")

def main_loop():
    LOGGER.info("🚀 Monitoring (fused) ...")
    # load persisted suppression state so restarts preserve recent suppression counts
    try:
        _load_suppression_cache()
    except Exception:
        LOGGER.warning("Could not load suppression cache")
    last_size = 0
    while True:
        try:
            if not os.path.exists(PATH.tradingview_log):
                time.sleep(TV.check_interval_sec)
                continue

            last_size, new_lines = _iter_new_lines(PATH.tradingview_log, last_size)
            if not new_lines:
                time.sleep(TV.check_interval_sec)
                continue

            for raw in new_lines:
                try:
                    rec = json.loads(raw)
                except Exception:
                    continue

                data = rec.get("data", {})
                symbol = data.get("symbol")
                price = float(data.get("price")) if data.get("price") is not None else None
                ts = data.get("time") or rec.get("timestamp")
                signal = data.get("signal")

                if not symbol or not ts:
                    continue

                # stale check: if payload time is older than REL.stale_input_sec, skip
                epoch_ts = _parse_ts_to_epoch(ts)
                if epoch_ts is not None:
                    import time as _t
                    now = _t.time()
                    if now - epoch_ts > REL.stale_input_sec:
                        LOGGER.warning(f"⏳ Skipped stale alert for {symbol} (age {now - epoch_ts:.0f}s)")
                        mark_processed(symbol, ts, price, signal, reason="stale")
                        continue

                # NOTE: delay duplicate check until we have the final entry price
                # (after screener / price-mismatch logic) so that replacements
                # by screener don't create different keys and allow duplicates.

                # screener (TV→yfinance)
                screener = get_screener_auto(symbol)
                if screener:
                    LOGGER.info(f"📊 Screener for {symbol}: src={screener.get('source')} used={screener.get('symbol_used')} ATR={screener.get('ATR')}")
                else:
                    LOGGER.warning(f"⚠️ Screener not available for {symbol}")

                # 先物ティッカー検出の警告 — screener の symbol_used が =F で終わる、または既知の先物記号の場合はログ出力
                sc = screener or {}
                sym_used = str(sc.get("symbol_used", ""))
                if sym_used.endswith("=F") or sym_used in {"SI=F","GC=F","NG=F","CL=F","HG=F"}:
                    LOGGER.warning(f"⚠️ Screener uses FUTURES ticker ({sym_used}) — entry_price と単位不一致の可能性")

                # news_score (将来: 経済カレンダーAPIで置換)
                news_score = 1.5

                # rating算出（screener込み）
                out = analyze_signal(data, news_score, None, screener)
                rating = out["rating"]
                meta = out["meta"] | ({"screener": screener} if screener else {})

                decision = _classify_decision(rating)

                # screener が先物ティッカーを返す場合は screener.price を entry に使わない（incoming_payload.price を優先）
                sc = screener or {}
                sc_sym = str(sc.get("symbol_used", ""))
                screener_price = None
                if sc and sc.get("price") is not None:
                    # 先物ティッカー判定
                    if sc_sym.endswith("=F") or sc_sym in {"SI=F","GC=F","NG=F","CL=F","HG=F"}:
                        LOGGER.warning(f"⚠️ Ignoring screener.price for futures ticker {sc_sym}")
                        screener_price = None
                    else:
                        screener_price = sc.get("price")

                entry = price if price is not None else screener_price
                if entry is None:
                    mark_processed(symbol, ts, price, signal)
                    LOGGER.warning(f"⚠️ Entry price missing for {symbol}, skip.")
                    continue

                # If both payload price and screener price exist, prefer screener when mismatch exceeds threshold
                try:
                    if price is not None and screener_price is not None:
                        p1 = float(price)
                        p2 = float(screener_price)
                        if p2 != 0:
                            rel = abs(p1 - p2) / abs(p2)
                            if rel > REL.price_mismatch_pct:
                                LOGGER.warning(f"⚠️ Price mismatch for {symbol}: payload={p1} screener={p2} rel={rel:.4f} -> preferring screener")
                                entry = screener_price
                except Exception:
                    pass

                # suppression: don't generate same decision too often
                now_ts = time.time()
                s_key = _suppression_key(symbol, decision, entry)
                cnt = _prune_and_count(s_key, now_ts)
                if cnt >= REL.suppression_max_count:
                    LOGGER.warning(f"🚫 Suppressed {decision} for {symbol} @{entry} (count {cnt} in {REL.suppression_window_sec}s)")
                    # record suppressed with the final entry for traceability
                    mark_processed(symbol, ts, entry, signal, reason="suppressed")
                    _record_suppression(s_key, now_ts)
                    continue

                # Use final entry price when checking processed state to avoid
                # duplicate IFDs caused by payload vs screener price differences.
                if has_been_processed(symbol, ts, entry, signal):
                    LOGGER.warning(f"⚠️ Skipped duplicate {symbol} @{ts} (entry={entry})")
                    mark_processed(symbol, ts, entry, signal, reason="duplicate_guard")
                    continue

                # Mark as processing before generating IFD to avoid near-duplicate double-processing
                try:
                    mark_processed(symbol, ts, entry, signal, reason="processing")
                except Exception as e:
                    LOGGER.warning(f"⚠️ mark_processed failed before IFD for {symbol}: {e}")
                else:
                    # record that we processed/generated (processing) so suppression
                    # counters reflect generated events and can be persisted
                    try:
                        _record_suppression(s_key, now_ts)
                    except Exception:
                        LOGGER.debug("failed to record suppression for processing")

                try:
                    ifd = generate_ifd(symbol, entry, decision, rating, meta)
                    # persist incoming raw payload for traceability
                    line = {"timestamp": datetime.now(timezone.utc).isoformat(), "incoming_payload": data, **ifd}
                    _write_ifd(line)

                    # update processed record with success (use final entry)
                    try:
                        mark_processed(symbol, ts, entry, signal, reason="ifd_written")
                    except Exception:
                        LOGGER.warning(f"⚠️ mark_processed update failed after IFD for {symbol}")

                    subject = f"🚨 {decision} - {symbol}"
                    body = (f"{symbol} @{entry}\n"
                            f"Rating: {rating:.2f}\n"
                            f"TP: {ifd['take_profit']} / SL: {ifd['stop_loss']}\n"
                            f"ScreenerSrc: {screener.get('source') if screener else 'NA'}\n"
                            f"Time: {ts}\n")
                    _send_mail(subject, body)

                except Exception as e:
                    LOGGER.error(f"❌ IFD generation failed for {symbol}: {e}")
                    # mark as error to avoid continuous retry storms; operator can re-run if needed
                    try:
                        mark_processed(symbol, ts, entry, signal, reason="error")
                    except Exception:
                        LOGGER.warning(f"⚠️ mark_processed error mark failed for {symbol}")
                    continue

        except KeyboardInterrupt:
            LOGGER.info("👋 Stopped.")
            break
        except Exception as e:
            LOGGER.error(f"❌ Loop error: {e}")
            time.sleep(TV.check_interval_sec)

if __name__ == "__main__":
    main_loop()
