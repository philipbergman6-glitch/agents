"""Narration eval harness: recorded narrations against the engine's numbers.

The personas may only *describe* what the engine computed. This harness
replays every recorded panel narration under research/panel-review/ against
the diagnoses the engine produces today from the same pinned snapshot, and
checks three things:

(a) every `data_quality.warnings[].code` a whale's diagnosis carries is
    mentioned in the narration (through a small code -> phrase vocabulary,
    since personas speak English, not codes);
(b) the pinned verbatim strings the portfolio persona must reproduce are
    present in any recorded portfolio narration — none is recorded yet, so
    today this only proves the extractor reads them out of the prompt;
(c) every number in the narration (two or more significant digits, not a
    year or a date) appears among the numeric values of the diagnoses, up
    to the narration's own rounding and % / $B / $M presentation.

A narration that fails (c) is a persona leaking or inventing a figure — the
exact failure mode the design forbids. Cases that cannot pass today are
marked xfail(strict=True) with the leaked numbers listed in the reason, so
they stay visible instead of being quietly weakened.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

from whale_engine.errors import MissingDataError
from whale_engine.scorers import buffett, graham, lynch

from conftest import SNAPSHOTS

REPO = Path(__file__).resolve().parents[2]
PANEL_REVIEW = REPO / "research" / "panel-review"
PORTFOLIO_REVIEW = REPO / "research" / "portfolio-review"
PORTFOLIO_PROMPT = REPO / ".claude" / "agents" / "portfolio.md"

SCORERS = {"buffett": buffett, "graham": graham, "lynch": lynch}

# How a persona is allowed to say each warning code in plain English. A code
# without an entry is a harness bug, not a pass: the test fails on it.
CODE_VOCABULARY: dict[str, str] = {
    "ttm_stitched": r"stitched",
    "ttm_stale_window": r"stale|lag(?:ging|s)?\b",
    "stale_leg_dropped": r"stale .*dropped|dropped .*stale|stale (?:buyback|issuance|leg)",
    "fundamentals_stale_vs_price": r"days (?:older|fresher)|price is .* older|books (?:are|end)",
    "share_split_renormalized": r"split|renormali[sz]",
    "share_count_repaired": r"repair|share count",
    "share_series_unexplained_jump": r"unexplained|share count",
    "restatement_402": r"restat",
    "restatement_guard_unavailable": r"restat",
    "market_cap_manual_unverified": r"manual|override",
    "market_cap_unverifiable": r"uncorroborated|unverifi",
    "market_cap_reference_mismatch": r"market[- ]cap",
    "market_cap_witness_mismatch": r"market[- ]cap",
    "balance_identity": r"balance[- ]sheet identity|assets .* liabilities",
    "yfinance-crosscheck-unavailable": r"cross-check|uncorroborated",
    "filings_sidecar_extraction_failed": r"filings[- ]text|sidecar",
    "form4_fetch_failed": r"form 4|insider",
    "sic_unavailable": r"\bSIC\b|sector",
}


# ---------------------------------------------------------------------------
# recorded narrations <-> snapshots


def _recorded_panels() -> list[Path]:
    return sorted(PANEL_REVIEW.glob("*-panel.md"))


def _snapshot_for(panel: Path) -> Path:
    m = re.match(r"([A-Z]+)-(\d{4}-\d{2}-\d{2})(?:-snapshot)?-panel\.md$", panel.name)
    if m is None:
        raise ValueError(f"cannot pair {panel.name} with a snapshot")
    return SNAPSHOTS / f"{m.group(1)}-{m.group(2)}.json"


def _diagnoses(snapshot_path: Path) -> dict[str, dict | MissingDataError]:
    snapshot = json.loads(snapshot_path.read_text())
    out: dict[str, dict | MissingDataError] = {}
    for name, module in SCORERS.items():
        try:
            out[name] = module.diagnose(snapshot)
        except MissingDataError as e:
            out[name] = e
    return out


# ---------------------------------------------------------------------------
# (c) numbers


_NUMBER = re.compile(
    r"(?<![\w.])"  # not inside a word or a decimal
    r"(?P<sign>[-−+])?\$?(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"(?!\d|\.\d|-[A-Za-z0-9]|[A-Za-z]{2})"  # not a version, a date, or "10-K"
    r"\s?(?P<suffix>[TBMK%x]|/100)?"
)
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_FORMS = re.compile(r"\b(?:10-K|10-Q|8-K|Item \d+|FY\d{4})\b")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def narration_numbers(text: str) -> list[tuple[str, float, str | None]]:
    """(token, magnitude, suffix) for every number with >= 2 significant digits,
    excluding ISO dates, form names and bare years."""
    scrubbed = _FORMS.sub(" ", _DATE.sub(" ", text))
    scrubbed = _YEAR.sub(" ", scrubbed)
    found = []
    for m in _NUMBER.finditer(scrubbed):
        raw = m.group("num")
        digits = raw.replace(",", "").replace(".", "").lstrip("0")
        if len(digits) < 2:
            continue
        found.append((m.group(0).strip(), float(raw.replace(",", "")), m.group("suffix")))
    return found


def _walk_numbers(value, out: set[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        if math.isfinite(value):
            out.add(float(value))
    elif isinstance(value, str):
        for m in re.finditer(r"-?\d[\d,]*(?:\.\d+)?(?:e[+-]?\d+)?", value):
            try:
                out.add(float(m.group(0).replace(",", "")))
            except ValueError:
                pass
    elif isinstance(value, dict):
        for v in value.values():
            _walk_numbers(v, out)
    elif isinstance(value, list | tuple):
        for v in value:
            _walk_numbers(v, out)


def diagnosis_numbers(diagnoses: dict[str, dict | MissingDataError]) -> set[float]:
    out: set[float] = set()
    for d in diagnoses.values():
        if isinstance(d, dict):
            _walk_numbers(d, out)
        else:
            _walk_numbers(str(d), out)
    return {abs(v) for v in out}


def _tolerance(token_magnitude: float, raw: str) -> float:
    """Half a unit in the narration's last stated digit."""
    if "." in raw:
        decimals = len(raw.split(".")[1])
        return 0.5 * 10 ** (-decimals)
    return 0.5


def _candidates(magnitude: float, suffix: str | None) -> list[float]:
    scale = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}
    if suffix in scale:
        return [magnitude * scale[suffix]]
    if suffix == "%":
        return [magnitude, magnitude / 100.0]
    return [magnitude]


def number_leaks(text: str, engine: set[float]) -> list[str]:
    """Narration numbers with no engine value behind them, as tokens."""
    leaks = []
    for token, magnitude, suffix in narration_numbers(text):
        raw = token.lstrip("-−+$").rstrip("TBMK%x ").replace(",", "")
        ok = False
        for c in _candidates(magnitude, suffix):
            scaled_tol = _tolerance(magnitude, raw) * (c / magnitude if magnitude else 1)
            if suffix == "%" and c != magnitude:
                scaled_tol = _tolerance(magnitude, raw) / 100.0
            if any(abs(v - c) <= scaled_tol for v in engine):
                ok = True
                break
        if not ok:
            leaks.append(token)
    return leaks


# ---------------------------------------------------------------------------
# (b) pinned strings


def pinned_strings(prompt: Path = PORTFOLIO_PROMPT) -> list[re.Pattern]:
    """The blockquoted verbatim strings the portfolio persona must reproduce,
    turned into regexes with `<slot>` placeholders as wildcards."""
    patterns = []
    for line in prompt.read_text().splitlines():
        if not line.strip().startswith("> "):
            continue
        body = line.strip()[2:].strip().replace("`", "")
        parts = re.split(r"<[^>]+>", body)
        regex = r".+?".join(re.escape(p.strip()) for p in parts if p.strip())
        patterns.append(re.compile(regex, re.IGNORECASE | re.DOTALL))
    return patterns


# ---------------------------------------------------------------------------
# tests


# Recorded narrations that cannot satisfy (c) today, with the exact leaked
# tokens. strict=True: the moment a case passes, the entry must go; and
# test_xfail_reasons_are_current fails if the leaks drift from what is listed.
KNOWN_LEAKS: dict[str, tuple[list[str], str]] = {
    # The panel was recorded before the market-cap witness gate existed; the
    # engine now refuses this snapshot outright (the derived cap rests on a
    # 2010 share count, -86% off the witness), so every figure in the
    # narration is unbacked today. It stays as a record of why the gate exists.
    "MA-2026-07-29-panel.md": (
        ["*"],
        "engine hard-fails this snapshot today (market_cap witness gate): all three "
        "whales walk away, so every narrated number is unbacked",
    ),
    # Figurative number: "the verdicts still split 180 degrees". Not an
    # engine figure, and the contract makes no allowance for idiom.
    "MSFT-2026-07-29-panel.md": (
        ["180"],
        "narration leaks a figurative number: '180' (\"split 180 degrees\")",
    ),
}


def _param(panel: Path):
    known = KNOWN_LEAKS.get(panel.name)
    marks = [pytest.mark.xfail(strict=True, reason=known[1])] if known else []
    return pytest.param(panel, id=panel.name, marks=marks)


PANELS = _recorded_panels()
assert PANELS, "no recorded panel narrations under research/panel-review/"


@pytest.mark.parametrize("panel", [pytest.param(p, id=p.name) for p in PANELS])
def test_every_engine_warning_is_narrated(panel):
    text = panel.read_text()
    diagnoses = _diagnoses(_snapshot_for(panel))
    codes: set[str] = set()
    for d in diagnoses.values():
        if isinstance(d, dict):
            codes |= {w["code"] for w in d["data_quality"]["warnings"]}
    missing_vocabulary = sorted(c for c in codes if c not in CODE_VOCABULARY)
    assert not missing_vocabulary, f"no vocabulary for warning codes {missing_vocabulary}"
    unmentioned = sorted(
        c for c in codes if not re.search(CODE_VOCABULARY[c], text, re.IGNORECASE)
    )
    assert not unmentioned, f"{panel.name} never mentions warning(s) {unmentioned}"


@pytest.mark.parametrize("panel", [_param(p) for p in PANELS])
def test_every_narrated_number_comes_from_the_engine(panel):
    text = panel.read_text()
    engine = diagnosis_numbers(_diagnoses(_snapshot_for(panel)))
    leaks = number_leaks(text, engine)
    assert not leaks, f"{panel.name}: numbers with no engine value behind them: {leaks}"


@pytest.mark.parametrize("name", sorted(KNOWN_LEAKS))
def test_xfail_reasons_are_current(name):
    """An xfail entry must describe exactly today's leaks — no more, no less —
    so a new leak in an already-xfailed narration still fails the suite."""
    panel = PANEL_REVIEW / name
    expected, _ = KNOWN_LEAKS[name]
    leaks = number_leaks(panel.read_text(), diagnosis_numbers(_diagnoses(_snapshot_for(panel))))
    if expected == ["*"]:
        assert len(leaks) > 20, f"{name}: expected every number to leak, got {leaks}"
    else:
        assert leaks == expected, f"{name}: leaks {leaks} != documented {expected}"


def test_pinned_portfolio_strings_are_readable_from_the_prompt():
    patterns = pinned_strings()
    assert len(patterns) >= 8, "portfolio.md lost its blockquoted pinned strings"
    sample = (
        "All 3 pairs in this basket could be measured, so the same-bet check "
        "covers every pair in it."
    )
    assert any(p.search(sample) for p in patterns)


@pytest.mark.parametrize(
    "narration",
    [pytest.param(p, id=p.name) for p in sorted(PORTFOLIO_REVIEW.glob("*.md"))]
    or [pytest.param(None, id="none-recorded", marks=pytest.mark.skip(
        reason="no recorded portfolio narrations under research/portfolio-review/ yet"
    ))],
)
def test_recorded_portfolio_narrations_carry_the_pinned_strings(narration):
    text = narration.read_text()
    patterns = pinned_strings()
    # The methodology closer and the sector closer fire on every report.
    always = [p for p in patterns if "Pearson" in p.pattern or "SIC major group" in p.pattern]
    assert always, "expected the two always-on closers in the prompt"
    missing = [p.pattern[:60] for p in always if not p.search(text)]
    assert not missing, f"{narration.name} is missing pinned string(s): {missing}"


# ---------------------------------------------------------------------------
# harness self-checks


def test_number_extraction_ignores_dates_years_and_forms():
    text = "fetched 2026-07-29 (edgartools 5.43.0); Item 7, FY2025, the 10-K; 2 of 10 periods"
    tokens = [t for t, _, _ in narration_numbers(text)]
    assert tokens == ["10"]


def test_number_matching_allows_rounding_and_presentation():
    engine = {0.0635, 35_912_345_678.0, 1.9234, 53.0}
    assert number_leaks("margin of safety −6.35%. $35.9B; debt/equity 1.92; 53/100", engine) == []
    assert number_leaks("intrinsic value $41.2B", engine) == ["$41.2B"]
