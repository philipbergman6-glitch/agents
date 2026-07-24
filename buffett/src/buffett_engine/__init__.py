"""Deterministic Warren Buffett-style company-diagnosis engine.

Two-phase design: `fetch` (networked, EDGAR + yfinance -> pinned JSON snapshot)
and `diagnose` (offline, pure function of one snapshot). Numbers never come
from an LLM; the LLM only narrates the JSON this engine emits.
"""

__version__ = "0.1.0"
