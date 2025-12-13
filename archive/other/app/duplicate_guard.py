from __future__ import annotations
import json
import os
import time
import hashlib
from typing import Any

from .config import PATH, LOGGER

# Cache maps sha256 keys -> metadata
_CACHE: dict[str, dict[str, Any]] = {}
_LOADED = False

def _load():
    global _LOADED, _CACHE
    if _LOADED:
        return
    p = PATH.processed_cache
    try:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # support old format (list of keys) by converting to dict
                if isinstance(data, list):
                    _CACHE = {k: {"processed_at": 0, "legacy": True} for k in data}
                elif isinstance(data, dict):
                    _CACHE = data
                else:
                    _CACHE = {}
        else:
            _CACHE = {}
    except Exception as e:
        LOGGER.warning(f"processed_cache load error: {e}")
        _CACHE = {}
    _LOADED = True

def _save():
    p = PATH.processed_cache
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(_CACHE, f, ensure_ascii=False, indent=2)
    except Exception as e:
        LOGGER.error(f"processed_cache save error: {e}")

def _normalize_for_hash(symbol: str, ts: Any, price: Any, signal: Any) -> str:
    """Create a canonical JSON string for hashing. Omits volatile fields like raw ts if present as high-resolution strings."""
    payload = {
        "symbol": symbol,
        # price normalized
        "price": None,
        "signal": signal,
    }
    try:
        if price is None:
            payload["price"] = None
        else:
            p = float(price)
            # normalize decimals: large prices -> 2 decimals, small -> 4
            payload["price"] = round(p, 2) if abs(p) >= 100 else round(p, 4)
    except Exception:
        payload["price"] = str(price)

    # create deterministic JSON
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _make_key(symbol: str, ts: Any, price: Any, signal: Any) -> str:
    s = _normalize_for_hash(symbol, ts, price, signal)
    h = hashlib.sha256(s.encode('utf-8')).hexdigest()
    return h

def has_been_processed(symbol: str, ts: str, price: Any, signal: Any) -> bool:
    _load()
    key = _make_key(symbol, ts, price, signal)
    return key in _CACHE

def mark_processed(symbol: str, ts: str, price: Any, signal: Any, reason: str | None = None):
    _load()
    global _CACHE
    key = _make_key(symbol, ts, price, signal)
    _CACHE[key] = {"symbol": symbol, "timestamp": ts, "price": price, "signal": signal, "processed_at": time.time(), "reason": reason}
    # keep cache bounded
    if len(_CACHE) > 5000:
        # drop oldest entries
        keys = list(_CACHE.keys())[-4000:]
        _CACHE = {k: _CACHE[k] for k in keys}
    _save()
