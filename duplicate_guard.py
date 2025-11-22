import hashlib
import json
import os
from datetime import datetime

# Store a mapping key -> metadata to improve traceability
PROCESSED_CACHE_PATH = os.path.join("output", "processed_cache.json")
_KEEP_MAX = 1000  # keep only last N entries to bound file size


def _load() -> dict:
    if not os.path.exists(PROCESSED_CACHE_PATH):
        return {}
    try:
        with open(PROCESSED_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d: dict) -> None:
    os.makedirs(os.path.dirname(PROCESSED_CACHE_PATH), exist_ok=True)
    # keep size bounded
    try:
        # sort keys by processed_at and keep last _KEEP_MAX
        items = list(d.items())
        if len(items) > _KEEP_MAX:
            # items are (key, meta); meta may have processed_at
            items_sorted = sorted(items, key=lambda kv: kv[1].get("processed_at", ""))
            items = items_sorted[-_KEEP_MAX:]
        with open(PROCESSED_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(dict(items), f, ensure_ascii=False, indent=2)
    except Exception:
        # best-effort; ignore save errors
        pass


def _key(symbol: str, timestamp: str) -> str:
    return hashlib.md5(f"{symbol}-{timestamp}".encode()).hexdigest()


_processed = _load()  # dict: key -> meta


def has_been_processed(symbol: str, timestamp: str) -> bool:
    if not timestamp:
        return False
    return _key(symbol, timestamp) in _processed


def mark_processed(symbol: str, timestamp: str, reason: str = None) -> None:
    k = _key(symbol, timestamp)
    _processed[k] = {
        "symbol": symbol,
        "timestamp": timestamp,
        "processed_at": datetime.utcnow().isoformat(),
        "reason": reason,
    }
    _save(_processed)
