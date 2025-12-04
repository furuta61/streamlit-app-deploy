# thresholds.py  —  しきい値の外部読み込み & マージ

import json
from pathlib import Path
from typing import Dict, Any

# 既定値（本体のロジックに合わせてあります）
DEFAULTS = {
    "score_go": 0.8,
    "score_strong": 1.5,
    "rr_go": 1.5,
    "rr_strong": 2.0,
    "votes_go": 2,
    "votes_strong": 3,
    "vol_limit": 0.015,
    "drift_limit": 0.0008,
}

# 銘柄別の初期プリセット（必要ならここを触る）
PRESET = {
    "日本225": {"vol_limit": 0.010, "votes_strong": 4},
    "米国NQ100ミニ": {"vol_limit": 0.012, "votes_strong": 3},
    "ドイツ40": {"vol_limit": 0.010, "votes_strong": 3},
    "金スポット": {"vol_limit": 0.015, "votes_strong": 3},
}

CFG_PATH = Path("cfd_thresholds.json")  # ← ここに上書き用のJSONを置く

def _load_user_cfg() -> Dict[str, Any]:
    if CFG_PATH.exists():
        try:
            with CFG_PATH.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # 壊れたら既定にフォールバック
            return {}
    return {}

def get_cfg_for_symbol(symbol: str) -> Dict[str, Any]:
    """
    しきい値 = DEFAULTS → PRESET[symbol] → user_cfg[symbol] の順で上書き。
    user_cfg が無ければ PRESET のみ適用。
    """
    user_cfg = _load_user_cfg()
    cfg = DEFAULTS.copy()
    cfg.update(PRESET.get(symbol, {}))
    cfg.update((user_cfg.get(symbol) or {}))
    return cfg
