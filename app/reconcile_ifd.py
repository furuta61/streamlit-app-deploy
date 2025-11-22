from __future__ import annotations
from __future__ import annotations
import json, os, csv, datetime
from collections import defaultdict

IFD_PATH = "output/ifd_orders.jsonl"
OUT_CSV  = "output/ifd_reconcile.csv"

FUTURES_SUFFIX = ("=F", )
FUTURES_SYMBOLS = {"SI=F","GC=F","NG=F","CL=F","HG=F"}


def _parse_ts(ts_str: str) -> datetime.datetime | None:
    if not ts_str:
        return None
    try:
        # allow trailing Z
        s = ts_str
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(s)
    except Exception:
        try:
            # fallback: try without timezone
            return datetime.datetime.fromisoformat(ts_str)
        except Exception:
            return None


def run(days: int = 7):
    rows = []
    if not os.path.exists(IFD_PATH):
        print(f"⚠️ not found: {IFD_PATH}")
        return

    with open(IFD_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue

            ts = rec.get("timestamp")
            sym = rec.get("symbol")
            dec = rec.get("decision")
            rate = rec.get("rating")
            ep = rec.get("entry_price")

            inc = rec.get("incoming_payload") or {}
            inc_price = inc.get("price")
            inc_ts = inc.get("time")

            sc = (rec.get("screener") or {})
            sc_price = sc.get("price")
            sc_sym = sc.get("symbol_used") or sc.get("symbol") or ""
            sc_ts = sc.get("fetched_at")

            rows.append({
                "timestamp": ts,
                "symbol": sym,
                "decision": dec,
                "rating": rate,
                "entry_price": ep,
                "incoming_price": inc_price,
                "incoming_ts": inc_ts,
                "screener_price": sc_price,
                "screener_symbol": sc_sym,
                "screener_ts": sc_ts,
                "is_futures": (sc_sym in FUTURES_SYMBOLS) or (isinstance(sc_sym, str) and sc_sym.endswith(FUTURES_SUFFIX)),
            })

    # filter to recent `days` (default 7)
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    filtered = []
    for r in rows:
        parsed = _parse_ts(r.get("timestamp"))
        if parsed is None:
            continue
        # normalize naive datetimes to UTC
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        if parsed > since:
            filtered.append(r)

    rows = filtered

    if not rows:
        print(f"⚠️ no recent rows in {IFD_PATH} for last {days} days")
        return

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"✅ wrote: {OUT_CSV} (rows={len(rows)}) - recent {days} days")

    # 簡易統計（シンボル別の乖離）
    by_sym = defaultdict(list)
    for r in rows:
        ep = r.get("entry_price")
        ip = r.get("incoming_price")
        sp = r.get("screener_price")
        if isinstance(ep, (int, float)) and isinstance(sp, (int, float)) and ep and sp:
            by_sym[(r["symbol"], "screener")].append(abs(ep - sp) / ep)
        if isinstance(ep, (int, float)) and isinstance(ip, (int, float)) and ep and ip:
            by_sym[(r["symbol"], "incoming")].append(abs(ep - ip) / ep)

    print("\n=== 乖離の要約（平均%）=== ")
    for (sym, kind), arr in sorted(by_sym.items()):
        avg = (sum(arr) / len(arr)) * 100 if arr else 0
        print(f"{sym:8s} vs {kind:9s}: {avg:6.2f}% ({len(arr)} samples)")


if __name__ == "__main__":
    run()

if __name__ == "__main__":
    run()
