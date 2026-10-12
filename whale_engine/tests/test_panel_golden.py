"""Golden panel summaries over real pinned snapshots.

Two layers, as with the scorers and the portfolio layer:
- semantic expectations: the engine counts, the LLM never does — a walk-away
  is its own category, a validation ERROR walks every whale away, and a
  unanimous panel over a snapshot with any WARN finding is flagged suspect;
- exact golden output: the whole summary must match the committed JSON, so
  any unintended change to the shape, the counts, or the pinned string fails
  loudly. Changing panel v1 itself needs an owner-signed review and a
  `panel_version` bump:
      uv run python tests/make_golden_panel.py
"""

import importlib
import sys
import types

import pytest

import whale_engine.panel
import whale_engine.scorers
from whale_engine.panel import ENGINE_COUNT_PREFIX, PANEL_VERSION, PANEL_WHALES, build_panel
from whale_engine.scorers import WHALES

from conftest import load_golden_panel, load_panel_snapshot

# Named snapshot dates, not latest-wins: a golden must not change because
# someone refetched a ticker.
GOLDEN_PANELS = {
    # three bearish whales over a snapshot carrying routine WARN findings:
    # the unanimity guard fires
    "KO-2026-07-27": "unanimous-with-warnings",
    # Lynch refuses (debt unresolved) while Buffett and Graham score: one walk-away
    "CAVA-2026-07-27": "one-walk-away",
    # the market-cap witness artifact: a validation ERROR walks all three away
    "MA-2026-07-29": "all-walk-away",
    # bullish / neutral / bullish: a split panel, no guard
    "LULU-2026-07-27": "split",
}


def panel(name: str) -> dict:
    return build_panel(load_panel_snapshot(name))


@pytest.mark.parametrize("name", GOLDEN_PANELS)
def test_exact_golden_output(name):
    assert panel(name) == load_golden_panel(name)


@pytest.mark.parametrize("name", GOLDEN_PANELS)
def test_summary_is_deterministic(name):
    assert panel(name) == panel(name)


@pytest.mark.parametrize("name", GOLDEN_PANELS)
def test_counts_cover_the_full_three_and_nothing_else(name):
    result = panel(name)
    assert result["panel_version"] == PANEL_VERSION
    assert set(result["whales"]) == set(PANEL_WHALES)
    assert sum(result["counts"].values()) == len(PANEL_WHALES)
    assert set(result["counts"]) == {"bullish", "neutral", "bearish", "walked_away"}
    # No ratio, no weighting, no label (#89 objections 1 and 3).
    assert not {"label", "verdict", "ratio", "weighted"} & set(result)


@pytest.mark.parametrize("name", GOLDEN_PANELS)
def test_the_pinned_string_is_the_counts_verbatim(name):
    result = panel(name)
    c = result["counts"]
    assert result["engine_count"] == (
        f"{ENGINE_COUNT_PREFIX}bullish {c['bullish']}, neutral {c['neutral']}, "
        f"bearish {c['bearish']}, walked away {c['walked_away']}"
    )


def test_a_unanimous_panel_over_a_snapshot_with_warnings_is_suspect():
    result = panel("KO-2026-07-27")
    assert result["counts"] == {"bullish": 0, "neutral": 0, "bearish": 3, "walked_away": 0}
    assert result["data_quality_warnings"]
    assert result["unanimity_suspect"] is True
    assert result["engine_count"] == "Engine count: bullish 0, neutral 0, bearish 3, walked away 0"


def test_a_walk_away_is_its_own_category_with_the_reason():
    result = panel("CAVA-2026-07-27")
    lynch = result["whales"]["lynch"]
    assert lynch["walked_away"] is True
    assert "MissingDataError" == lynch["error"]
    assert "short_term_debt+long_term_debt" in lynch["reason"]
    assert lynch["signal"] is None and lynch["confidence"] is None and lynch["score"] is None
    assert lynch["rubric_version"] == 2
    assert result["counts"] == {"bullish": 0, "neutral": 0, "bearish": 2, "walked_away": 1}
    # Two scored whales agree and warnings exist: still suspect — the guard
    # is over the scored whales, not the full three.
    assert result["unanimity_suspect"] is True


def test_a_validation_error_walks_every_whale_away_and_cannot_be_unanimous():
    result = panel("MA-2026-07-29")
    assert all(w["walked_away"] for w in result["whales"].values())
    assert all("market_cap_witness" in w["reason"] or "witness" in w["reason"]
               for w in result["whales"].values())
    assert result["counts"] == {"bullish": 0, "neutral": 0, "bearish": 0, "walked_away": 3}
    assert result["unanimity_suspect"] is False


def test_a_split_panel_is_never_suspect():
    result = panel("LULU-2026-07-27")
    signals = {w: v["signal"] for w, v in result["whales"].items()}
    assert signals == {"buffett": "bullish", "graham": "neutral", "lynch": "bullish"}
    assert result["counts"] == {"bullish": 2, "neutral": 1, "bearish": 0, "walked_away": 0}
    assert result["data_quality_warnings"]
    assert result["unanimity_suspect"] is False


def test_each_scored_whale_carries_its_own_rubric_version_and_score():
    result = panel("LULU-2026-07-27")
    for whale in PANEL_WHALES:
        entry = result["whales"][whale]
        assert entry["walked_away"] is False
        assert entry["rubric_version"] >= 1
        assert {"total", "max", "pct"} <= set(entry["score"])
        assert isinstance(entry["confidence"], int)


def test_provenance_pins_the_snapshot_not_the_clock():
    result = panel("KO-2026-07-27")
    assert result["ticker"] == "KO"
    assert result["provenance"]["snapshot_fetched_at"] == "2026-07-27"
    assert "source" in result["provenance"]


@pytest.fixture
def fourth_scorer_registered():
    """A stub scorer registered in the scorer registry, with the panel module
    re-imported on top of it — what the engine looks like once a fourth whale
    ships diagnosable but has not yet joined the panel. Running the stub is
    itself a failure: the panel must not even call an unlisted scorer."""

    def diagnose(snapshot):
        raise AssertionError("the panel ran a scorer that is not on the panel")

    stub = types.ModuleType("whale_engine.scorers.stub")
    stub.diagnose = diagnose  # type: ignore[attr-defined]
    stub.RUBRIC_VERSION = 1  # type: ignore[attr-defined]
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "whale_engine.scorers.stub", stub)
        mp.setattr(whale_engine.scorers, "WHALES", (*WHALES, "stub"))
        yield importlib.reload(whale_engine.panel)
    importlib.reload(whale_engine.panel)


def test_panel_membership_is_the_panel_list_not_the_scorer_registry(
    fourth_scorer_registered,
):
    # the stub really is registered: the registry would hand it out
    assert whale_engine.scorers.get_diagnose("stub") is not None
    result = fourth_scorer_registered.build_panel(load_panel_snapshot("KO-2026-07-27"))
    assert list(result["whales"]) == ["buffett", "graham", "lynch"]
    assert result["provenance"]["whales"] == ["buffett", "graham", "lynch"]
    assert result == load_golden_panel("KO-2026-07-27")
