from __future__ import annotations
import os, datetime, csv, statistics
import requests
import smtplib
import ssl
try:
    import certifi
    _HAS_CERTIFI = True
except Exception:
    certifi = None
    _HAS_CERTIFI = False
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import EMAIL, LOGGER

WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")
OUT_CSV = "output/ifd_reconcile.csv"


def _read_csv(path: str):
    if not os.path.exists(path):
        LOGGER.warning(f"not found: {path}")
        return []
    rows = []
    with open(path, "r", newline="") as f:
        r = csv.DictReader(f)
        for rec in r:
            rows.append(rec)
    return rows


def _compute_stats(rows: list):
    total = len(rows)
    screener_diffs = []
    by_sym = {}
    for r in rows:
        try:
            ep = float(r.get("entry_price")) if r.get("entry_price") not in (None, "") else None
        except Exception:
            ep = None
        try:
            sp = float(r.get("screener_price")) if r.get("screener_price") not in (None, "") else None
        except Exception:
            sp = None
        if ep is not None and sp is not None and ep != 0:
            pct = abs(ep - sp) / ep * 100.0
            screener_diffs.append(pct)
            sym = r.get("symbol") or ""
            by_sym.setdefault(sym, []).append(pct)

    overall_avg = statistics.mean(screener_diffs) if screener_diffs else 0.0

    per_sym = []
    for sym, arr in by_sym.items():
        per_sym.append((sym, statistics.mean(arr), len(arr)))
    per_sym.sort(key=lambda x: x[1], reverse=True)
    top5 = per_sym[:5]
    return {
        "total_rows": total,
        "overall_avg_pct": overall_avg,
        "top5": top5,
    }


def _build_slack_text(stats: dict):
    lines = []
    lines.append(f"📊 IFD突合レポート (直近7日)")
    lines.append(f"合計: {stats['total_rows']}件")
    lines.append(f"平均乖離: {stats['overall_avg_pct']:.2f}%")
    lines.append("")
    lines.append("上位乖離5銘柄:")
    for i, (sym, avg, cnt) in enumerate(stats["top5"], start=1):
        lines.append(f"{i}. {sym} {avg:.2f}% ({cnt})")
    return "\n".join(lines)


def _build_html_email(stats: dict):
    html = [f"<h2>📊 IFD突合レポート（直近7日）</h2>", f"<p>合計: <b>{stats['total_rows']}</b>件<br>平均乖離: <b>{stats['overall_avg_pct']:.2f}%</b></p>", "<h3>上位乖離5銘柄</h3>", "<ol>"]
    for sym, avg, cnt in stats["top5"]:
        html.append(f"<li>{sym}: {avg:.2f}% ({cnt} samples)</li>")
    html.append("</ol>")
    html.append(f"<p>CSV: {OUT_CSV}</p>")
    return "\n".join(html)


def _send_slack(msg: str) -> bool:
    if not WEBHOOK:
        LOGGER.info("SLACK_WEBHOOK_URL not set; skipping Slack")
        return False
    try:
        requests.post(WEBHOOK, json={"text": msg}, timeout=10)
        LOGGER.info("Slack通知送信完了")
        return True
    except Exception as e:
        LOGGER.error(f"Slack送信失敗: {e}")
        return False


def _send_email(subject: str, html_body: str) -> bool:
    if not (EMAIL.from_addr and EMAIL.to_addr and EMAIL.app_password):
        LOGGER.info("Email config not set; skipping email send")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL.from_addr
        msg["To"] = EMAIL.to_addr
        part = MIMEText(html_body, "html", "utf-8")
        msg.attach(part)
        # build SSL context; prefer certifi bundle when available to avoid macOS cert issues
        if _HAS_CERTIFI:
            context = ssl.create_default_context(cafile=certifi.where())
        else:
            context = ssl.create_default_context()
        with smtplib.SMTP_SSL(EMAIL.smtp_host, EMAIL.smtp_port, context=context) as server:
            server.login(EMAIL.from_addr, EMAIL.app_password)
            server.sendmail(EMAIL.from_addr, [EMAIL.to_addr], msg.as_string())
        LOGGER.info("Email送信完了")
        return True
    except Exception as e:
        LOGGER.error(f"Email送信失敗: {e}")
        return False


def notify_report():
    rows = _read_csv(OUT_CSV)
    if not rows:
        print(f"⚠️ {OUT_CSV} が見つからないかデータが空です")
        return
    stats = _compute_stats(rows)
    slack_text = _build_slack_text(stats)
    html = _build_html_email(stats)

    # Try Slack first (if configured)
    sent_slack = _send_slack(slack_text)

    # Always try email if email config present
    subject = f"📊 IFD突合レポート {datetime.date.today()}"
    sent_email = _send_email(subject, html)

    # Terminal output summary
    print("--- notify_summary ---")
    print(slack_text)
    print(f"Slack sent: {sent_slack}, Email sent: {sent_email}")


if __name__ == "__main__":
    notify_report()
