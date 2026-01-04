"""Render/Streamlit entrypoint.

This shim keeps the repository structure intact while allowing Render to run:
  streamlit run app.py --server.port $PORT --server.address 0.0.0.0

The actual UI lives in `quiz_pack/app.py`.
"""

from __future__ import annotations

# Importing executes the Streamlit app (it defines the UI at import time).
import quiz_pack.app  # noqa: F401
