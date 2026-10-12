"""Offline panel layer: one snapshot -> one deterministic agreement summary.

Implements panel v1 (map #97; resolves #89).

What this layer is, and is not: each whale scores the company under its own
rubric; this layer runs all three over the *same* pinned snapshot and reports
what they said, side by side, with the raw counts. It renders no verdict:
no GO/NO-GO label, no ratio, no confidence weighting, no averaged score
(#89 objections 1, 2, 3, 5, 6). The engine counts so the narrator never has
to — `/panel` reproduces `engine_count` verbatim and synthesises prose around
it, never arithmetic.

Determinism contract, same as every scorer: a pure function of the snapshot
handed in — no network, no clock, no randomness. Byte-identical output from
the same snapshot, whatever day it is.

Locked shape (panel v1 — changing it requires an owner-signed review, the
rubric-v2 precedent, and a `panel_version` bump):

- `whales.<name>`: `signal`, `confidence`, `score`, `rubric_version` for a
  scored whale; for a walk-away the same keys null, `walked_away: true`,
  the exception class and its message. A walk-away is `MissingDataError`
  *only* — any other exception is an engine bug and propagates.
- `counts`: `bullish / neutral / bearish / walked_away` over the full three.
- `engine_count`: the pinned narration string, built from `counts` alone.
- `data_quality_warnings`: the snapshot's WARN findings under the default
  validation arrays (whale-agnostic; a scorer's own `data_quality` block may
  differ — Graham inspects the quarterly array only).
- `unanimity_suspect`: true iff at least one whale scored, every scored whale
  shares a signal, and any warning exists (#89 objection 4). Three
  walk-aways are not unanimity.

Whale rubrics are untouched (#40): this module reads their output, never
their inputs.
"""

from __future__ import annotations

import copy
from importlib import import_module

from . import validation
from .errors import MissingDataError
from .fetch import SECTOR_SNAPSHOT_KIND
from .scorers import WHALES, get_diagnose

PANEL_VERSION = 1

SIGNALS = ("bullish", "neutral", "bearish")
WALKED_AWAY = "walked_away"

# The narration string, pinned verbatim: the skill reproduces this line word
# for word. Wording versions with the panel; owner review covers the wording.
ENGINE_COUNT_PREFIX = "Engine count: "


def engine_count_line(counts: dict[str, int]) -> str:
    return (
        f"{ENGINE_COUNT_PREFIX}bullish {counts['bullish']}, neutral {counts['neutral']}, "
        f"bearish {counts['bearish']}, walked away {counts[WALKED_AWAY]}"
    )


def _rubric_version(whale: str) -> int:
    return import_module(f"whale_engine.scorers.{whale}").RUBRIC_VERSION


def _run_whale(whale: str, snapshot: dict) -> dict:
    """One whale's row. Each scorer gets its own deep copy so no scorer can
    see another's side effects — the panel must equal three independent
    `diagnose` runs."""
    try:
        result = get_diagnose(whale)(copy.deepcopy(snapshot))
    except MissingDataError as e:
        return {
            "walked_away": True,
            "error": type(e).__name__,
            "reason": str(e),
            "signal": None,
            "confidence": None,
            "score": None,
            "rubric_version": _rubric_version(whale),
        }
    if result["signal"] not in SIGNALS:
        raise ValueError(f"{whale}: unknown signal {result['signal']!r}")
    return {
        "walked_away": False,
        "error": None,
        "reason": None,
        "signal": result["signal"],
        "confidence": result["confidence"],
        "score": result["score"],
        "rubric_version": result["rubric_version"],
    }


def build_panel(snapshot: dict) -> dict:
    if snapshot.get("kind") == SECTOR_SNAPSHOT_KIND:
        raise MissingDataError(
            f"{snapshot.get('ticker')}: sector-only snapshot (SIC code only, for the "
            "portfolio layer) — there is nothing here for any whale to score"
        )
    for key in ("ticker", "fetched_at", "source"):
        if key not in snapshot:
            raise MissingDataError(f"snapshot is missing {key!r}")

    whales = {whale: _run_whale(whale, snapshot) for whale in WHALES}

    counts = {signal: 0 for signal in SIGNALS}
    counts[WALKED_AWAY] = 0
    for row in whales.values():
        counts[WALKED_AWAY if row["walked_away"] else row["signal"]] += 1

    findings, checks_run = validation.run_checks(snapshot)
    warnings = [f for f in findings if f["severity"] == validation.WARN]

    scored_signals = {row["signal"] for row in whales.values() if not row["walked_away"]}
    unanimity_suspect = len(scored_signals) == 1 and bool(warnings)

    return {
        "panel_version": PANEL_VERSION,
        "ticker": snapshot["ticker"],
        "whales": whales,
        "counts": counts,
        "engine_count": engine_count_line(counts),
        "data_quality_warnings": warnings,
        "unanimity_suspect": unanimity_suspect,
        "provenance": {
            "snapshot_fetched_at": snapshot["fetched_at"],
            "source": snapshot["source"],
            "market_cap_source": snapshot.get("market_cap_source"),
            "validation_checks_run": checks_run,
            "whales": list(WHALES),
        },
    }
