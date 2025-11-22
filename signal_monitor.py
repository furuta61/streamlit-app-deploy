#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
signal_monitor.py – CFD3 Pro System (ver.2025-11)
Author: OTOMI
Description:
  TradingView から receiver.py 経由で保存された tradingview.jsonl を監視し、
  STRONG_GO / GO シグナルを検出すると Gmail 通知と IFD 自動生成を行う。

  対応銘柄: JP225 / NQ100 / XAUUSD / XAGUSD / NGAS / GER40
  STRONG_GO → TP +1200 / GO → TP +700 / SL -700
"""

import os
import json
import time
import smtplib
import sys
from email.mime.text import MIMEText
from datetime import datetime
from mygpt_strategy import generate_ifd, analyze_signal
from market_data_tradingview import get_tv_screener_data_auto as get_tv_screener_data
from duplicate_guard import has_been_processed, mark_processed
from signal_classifier import classify_signal
from app.news_collector import fetch_news
# GMO 自動発注モジュール（Seleniumラッパー）
try:
    from app.gmo_order_executor import execute_gmo_order
except Exception:
    execute_gmo_order = None

# ====== 基本設定 ======
TARGET_SYMBOLS = ["JP225", "NQ100", "XAUUSD", "XAGUSD", "NGAS", "GER40"]
TRADINGVIEW_LOG = os.path.join(os.path.dirname(__file__), "output", "tradingview.jsonl")
CHECK_INTERVAL = 3  # 秒ごとに監視

# ====== メール設定（環境変数から取得） ======
# 互換: `.env.example` は ALERT_EMAIL_USER/ALERT_EMAIL_HOST/ALERT_EMAIL_PORT を想定。
# 既存コードは ALERT_EMAIL_FROM と SMTP_HOST/SMTP_PORT もサポート。
EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM") or os.getenv("ALERT_EMAIL_USER")
EMAIL_TO = os.getenv("ALERT_EMAIL_TO")
EMAIL_PASS = os.getenv("ALERT_EMAIL_PASS")

# =======================================================

def send_mail(subject: str, body: str):
    """Gmail通知送信"""
    # 強制ドライラン（テスト用）: ALERT_EMAIL_DRY_RUN=1 なら送信せず出力のみ
    if os.getenv("ALERT_EMAIL_DRY_RUN") in ("1", "true", "True"):
        print("[Email DryRun]", subject)
        print(body)
        return
    if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PASS]):
        print("⚠️ 環境変数 ALERT_EMAIL_* が設定されていません。メール送信をスキップします。")
        print(f"[DryRun] Subject: {subject}\n{body}")
        return
    # Allow overriding SMTP host/port for local testing (no auth) via env vars
    # 互換読み: SMTP_HOST/SMTP_PORT または ALERT_EMAIL_HOST/ALERT_EMAIL_PORT
    smtp_host_env = os.getenv("SMTP_HOST") or os.getenv("ALERT_EMAIL_HOST")
    smtp_port_env = os.getenv("SMTP_PORT") or os.getenv("ALERT_EMAIL_PORT")
    SMTP_HOST = smtp_host_env
    SMTP_PORT = int(smtp_port_env) if smtp_port_env else None
    SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "1") in ("1", "true", "True")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    try:
        if SMTP_HOST and SMTP_PORT:
            # connect to specified SMTP (use plain SMTP, optional STARTTLS if requested)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
                smtp.set_debuglevel(1)
                # try STARTTLS if requested and server allows
                try:
                    smtp.starttls()
                except Exception:
                    pass
                # login if credentials provided
                try:
                    smtp.login(EMAIL_FROM, EMAIL_PASS)
                except Exception:
                    # ignore login errors for local debug server
                    pass
                smtp.send_message(msg)
        else:
            # default: Gmail SMTP over SSL
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(EMAIL_FROM, EMAIL_PASS)
                smtp.send_message(msg)
        print(f"📨 Mail sent: {subject}")
    except Exception as e:
        print(f"❌ Mail send failed: {e}")


def parse_tradingview_line(line: str):
    """tradingview.jsonl から payloadを抽出"""
    try:
        entry = json.loads(line)
        data = entry.get("data") or entry.get("payload") or entry
        symbol = str(data.get("symbol") or data.get("s")).upper()
        signal = str(data.get("signal") or data.get("decision") or "").upper()
        price = float(data.get("price", 0))
        timestamp = data.get("time") or entry.get("timestamp")
        return symbol, signal, price, timestamp
    except Exception:
        return None, None, None, None


def monitor_signals():
    """TradingViewシグナルを監視し、自動アクションを実行"""
    print("🚀 Monitoring for STRONG_GO / GO (仕込み時間) signals...")

    last_size = 0
    seen_lines = set()

    while True:
        try:
            if not os.path.exists(TRADINGVIEW_LOG):
                time.sleep(CHECK_INTERVAL)
                continue

            with open(TRADINGVIEW_LOG, "r", encoding="utf-8") as f:
                lines = f.readlines()

            if len(lines) == 0:
                time.sleep(CHECK_INTERVAL)
                continue

            new_lines = lines[last_size:]
            last_size = len(lines)

            for line in new_lines:
                if not line.strip() or line in seen_lines:
                    continue
                seen_lines.add(line)

                symbol, signal, price, timestamp = parse_tradingview_line(line)
                if symbol not in TARGET_SYMBOLS:
                    continue

                # If incoming payload has a raw 'signal' string we still pass it to the classifier
                # classifier will respect explicit STRONG_GO / GO labels but can also infer from payload
                payload = None
                try:
                    payload = json.loads(line)
                except Exception:
                    payload = {}

                # print short receipt for operator visibility
                try:
                    print("📩 Received:", json.dumps(payload, ensure_ascii=False))
                except Exception:
                    print("📩 Received: <unserializable payload>")

                inferred = classify_signal(payload)

                # --- Fetch screener data (optional) using auto fallback ---
                screener_data = None
                try:
                    screener_data = get_tv_screener_data(symbol)
                    if screener_data:
                        # user-friendly message: show base symbol and used candidate
                        used = screener_data.get('used_symbol') or screener_data.get('symbol')
                        exch = screener_data.get('exchange')
                        print(f"📊 Screener data for {symbol}: (used={used} exch={exch}) {screener_data}")
                    else:
                        print(f"⚠️ Screener data not available for {symbol}")
                except Exception as e:
                    print(f"❌ Screener fetch error for {symbol}: {e}")
                    screener_data = None

                # call the stronger news+technical analyzer which will return a decision and rating
                try:
                    # pass screener inside payload so analyze_signal can use it
                    payload_for_analysis = dict(payload) if isinstance(payload, dict) else {}
                    # Ensure the original signal label is forwarded to the analyzer
                    try:
                        payload_for_analysis['signal'] = signal
                    except Exception:
                        pass
                    if screener_data:
                        payload_for_analysis['screener'] = screener_data
                    # --- Fetch recent news and add to payload_for_analysis so analyzer can use it ---
                    try:
                        news_result = fetch_news(symbol)
                        # fetch_news may return either a list (legacy) or a dict with articles+sentiment
                        if isinstance(news_result, dict):
                            articles = news_result.get('articles', []) or []
                            sentiment_score = news_result.get('sentiment_score', 0.0)
                            payload_for_analysis['news_items'] = articles
                            payload_for_analysis['sentiment_score'] = sentiment_score
                            news_items = articles
                        else:
                            payload_for_analysis['news_items'] = news_result or []
                            news_items = news_result or []
                    except Exception:
                        news_items = []
                    # call root-level analyze_signal(symbol, data)
                    analysis = analyze_signal(symbol, payload_for_analysis)
                except Exception as e:
                    print(f"⚠️ analyze_signal failed for {symbol}: {e}")
                    analysis = {"decision": inferred or "GO", "rating": None, "news_refs": [], "tech_score": None}

                decision = analysis.get("decision") or (inferred or "GO")

                # --- duplicate guard ---
                if not timestamp:
                    timestamp = datetime.utcnow().isoformat()
                if has_been_processed(symbol, timestamp):
                    print(f"⚠️ Skipped duplicate signal for {symbol} @ {timestamp}")
                    continue
                mark_processed(symbol, timestamp)
                # -----------------------

                # generate_ifd returns the order dict; attach analysis results into meta
                meta = {
                    "rating": analysis.get("rating"),
                    "rating_adjustment": analysis.get("rating_adjustment"),
                    "news_refs": analysis.get("news_refs"),
                    "tech_score": analysis.get("tech_score"),
                }
                # If we fetched news_items earlier, populate meta fields (override/augment analyzer results)
                try:
                    news_items = news_items if 'news_items' in locals() else []
                    meta["news_refs"] = [n.get("title") for n in news_items]
                    meta["news_count"] = len(news_items)
                    meta["news_score"] = min(len(news_items) * 0.2, 3.0)
                    # if sentiment was attached by fetch, propagate it
                    if 'sentiment_score' in payload_for_analysis:
                        meta['sentiment_score'] = payload_for_analysis.get('sentiment_score')
                except Exception:
                    pass
                if screener_data:
                    meta["screener"] = screener_data

                # attach original incoming signal and a small payload snapshot for traceability
                try:
                    meta['original_signal'] = signal
                    meta['incoming_ts'] = timestamp
                    # keep a small snapshot to avoid excessively large IFD lines
                    small_keys = ['symbol', 'price', 'signal', 'time']
                    small = {k: payload.get(k) for k in small_keys if isinstance(payload, dict) and k in payload}
                    if small:
                        meta['incoming_payload'] = small
                    else:
                        # fallback: include top-level payload if it's small
                        if isinstance(payload, dict):
                            meta.setdefault('incoming_payload', {k: payload.get(k) for k in list(payload)[:5]})
                except Exception:
                    pass

                # generate IFD using root mygpt_strategy.generate_ifd (decision + meta)
                order = generate_ifd(symbol, price, decision, meta=meta)
                # additional log: if meta includes screener data, print a compact message
                if meta and meta.get('screener'):
                    try:
                        print(f"📊 Screener data for {symbol}: (source={meta['screener'].get('source')}) {meta['screener']}")
                    except Exception:
                        pass

                # Console-friendly summary for quick inspection
                print("✅ IFD generated:", json.dumps({
                    "symbol": order.get("symbol"),
                    "decision": order.get("decision"),
                    "take_profit": order.get("take_profit"),
                    "stop_loss": order.get("stop_loss"),
                }, ensure_ascii=False))

                # --- 自動発注: decision が GO / STRONG_GO の場合のみ実行 ---
                try:
                    if execute_gmo_order and decision in ["STRONG_GO", "GO"]:
                        print(f"🚀 GMOへ自動発注を開始: {symbol}")
                        # 注文内容は generate_ifd の戻り値（order）を渡す
                        try:
                            execute_gmo_order(order)
                        except Exception as e:
                            print(f"❌ 自動発注でエラー: {e}", file=sys.stderr)
                except Exception:
                    # safety: do not let auto-ordering break the monitor loop
                    pass

                rating = analysis.get("rating")
                tech_score = analysis.get("tech_score")
                news_score = analysis.get("news_score")
                news_refs = analysis.get("news_refs") or []
                print(f"⭐ rating: {rating} (tech={tech_score}, news={news_score})")
                if news_refs:
                    print("📰 News refs:")
                    for r in news_refs:
                        print(f"  - {r}")

                md = (
                    f"- Symbol: {order['symbol']}\n"
                    f"- Decision: {order['decision']}\n"
                    f"- Entry: {order['entry_price']}\n"
                    f"- TP: {order['take_profit']}\n"
                    f"- SL: {order['stop_loss']}\n"
                    f"- Rating: {order.get('rating')}\n"
                    f"- Time: {order.get('timestamp')}\n"
                )

                # Add auto-order status (monitor-side dry-run visibility)
                auto_enabled = os.getenv("GMO_AUTOMATION_ENABLED") == "1"
                if execute_gmo_order is None:
                    auto_status = "自動発注モジュール未ロード（gmo_order_executor が利用できません）。IFD は生成されますが自動発注は行われません。"
                elif not auto_enabled:
                    auto_status = "自動発注は Dry-run（GMO_AUTOMATION_ENABLED != 1）。IFD は生成されますが実行されません。"
                else:
                    auto_status = "自動発注モード: ON（GMO_AUTOMATION_ENABLED=1）。IFD 生成後に自動発注を試みます。"

                subject = f"🚨 {decision} - {symbol}"
                body = (
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"{symbol} @ {price}\n\n"
                    f"{md}\n\n"
                    f"※IFD自動生成済み: output/ifd_orders.jsonl\n"
                    f"※自動発注ステータス: {auto_status}\n"
                    f"\n※【承認手順】自動発注を有効化して本番発注するには環境変数を設定してください: export GMO_AUTOMATION_ENABLED=1 （実行前に要確認、少量で試験）。\n"
                )
                send_mail(subject, body)

        except KeyboardInterrupt:
            print("\n🛑 Monitor stopped by user.")
            break
        except Exception as e:
            print(f"⚠️ Error in monitor loop: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    monitor_signals()

