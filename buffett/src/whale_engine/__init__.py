"""Deterministic whale-style company-diagnosis engine.

Two-phase design: `fetch` (networked, EDGAR + yfinance -> pinned JSON snapshot,
whale-agnostic raw data) and `diagnose` (offline, pure function of one snapshot,
scored by the selected whale's rubric in scorers/). Numbers never come from an
LLM; the LLM only narrates the JSON this engine emits.
"""

__version__ = "0.2.0"
