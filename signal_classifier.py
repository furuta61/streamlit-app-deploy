"""signal_classifier.py
Simple, transparent rules to decide between 'GO' and 'STRONG_GO'.

Contract:
  - classify_signal(payload: dict) -> str
    returns either 'STRONG_GO' or 'GO'

Rules (in order):
 1. If payload explicitly contains 'STRONG_GO' or 'GO' (case-insensitive), honor it.
 2. If payload contains numeric keys 'confidence' or 'score' or 'strength' (0..1 or 0..100),
    use thresholds: >=0.75 => STRONG_GO, >=0.5 => GO, else treat as GO.
 3. If payload contains 'indicator' or 'tags' with words like 'breakout'/'strong', prefer STRONG_GO.
 4. Fallback: treat as GO (conservative).

This module is intentionally simple and easily tunable. Put more advanced logic
here (ensemble checks, historic volatility) when available.
"""
from typing import Any, Dict


def _get_numeric_score(payload: Dict[str, Any]):
    # look for common numeric fields
    for k in ("confidence", "score", "strength", "confidence_score"):
        v = payload.get(k)
        if v is None:
            continue
        try:
            fv = float(v)
        except Exception:
            continue
        # normalize if appears to be 0..100
        if fv > 1 and fv <= 100:
            fv = fv / 100.0
        return fv
    return None


def _text_has_any(text: str, words):
    if not text:
        return False
    t = text.lower()
    return any(w in t for w in words)


def classify_signal(payload: Dict[str, Any]) -> str:
    """Return 'STRONG_GO' or 'GO' based on payload heuristics.

    payload: tradingview payload or similar dict
    """
    # 1) explicit label
    for key in ("signal", "decision", "action"):
        v = payload.get(key)
        if not v:
            continue
        s = str(v).upper()
        if "STRONG" in s:
            return "STRONG_GO"
        if s.strip() == "GO":
            return "GO"

    # 2) numeric score
    score = _get_numeric_score(payload)
    if score is not None:
        if score >= 0.75:
            return "STRONG_GO"
        if score >= 0.5:
            return "GO"

    # 3) indicator / tags hints
    text_fields = []
    for k in ("note", "text", "indicator", "tags", "comment"):
        v = payload.get(k)
        if not v:
            continue
        if isinstance(v, (list, tuple)):
            text_fields.extend([str(x) for x in v])
        else:
            text_fields.append(str(v))

    combined = " ".join(text_fields)
    if _text_has_any(combined, ["breakout", "strong", "bullish", "confirm", "momentum"]):
        return "STRONG_GO"

    # fallback conservative
    return "GO"
