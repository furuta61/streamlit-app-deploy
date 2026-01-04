"""Top-level alias for the grammar rules.

Some deployment guides assume `rules.py` exists at repo root.
The canonical data lives in `quiz_pack/backend/rules.py`.
"""

from __future__ import annotations

from quiz_pack.backend.rules import rules

__all__ = ["rules"]
