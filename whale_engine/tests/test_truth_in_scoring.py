"""flagged data must not score, trends must see the present.

The BLDR-2026-07-28 snapshot is the audit artifact behind the ticket: its
issuance leg is a TTM window ending 2015-12-31 (stale by a decade), its ~$3.7B
of real debt resolves under no pre-truth-in-scoring tag, and its latest fundamentals lag
the price by 119 days. The regression tests pin the post-fix behavior on that
exact snapshot.
"""

import copy
import json

import pytest

from whale_engine import validation
from whale_engine.errors import MissingDataError
from whale_engine.fetch import _realign_tags
from whale_engine.scorers import buffett, graham

from conftest import SNAPSHOTS, load_snapshot

BLDR = json.loads((SNAPSHOTS / "BLDR-2026-07-28.json").read_text())


def _warn_codes(result):
    return [w["code"] for w in result["data_quality"]["warnings"]]


# ---------------------------------------------------------------------------
# BLDR regression (acceptance criteria of the ticket)


def test_bldr_management_point_not_from_stale_leg():
    """A2: the buyback point must come from the clean FY2025 annual figure,
    not the combine polluted by the 2015-window issuance leg."""
    result = buffett.diagnose(BLDR)
    mgmt = result["dimensions"]["management"]
    assert any("413,958,000" in d for d in mgmt["details"])
    assert not any("770,476,000" in d for d in mgmt["details"])
    assert any(
        f.startswith("stale_data: issuance_or_purchase_of_equity_shares") for f in result["flags"]
    )


def test_bldr_stale_window_warned_with_dimensions():
    result = buffett.diagnose(BLDR)
    stale = [w for w in result["data_quality"]["warnings"] if w["code"] == "ttm_stale_window"]
    assert stale and stale[0]["context"]["field"] == "issuance_or_purchase_of_equity_shares"
    assert stale[0]["dimensions_affected"] == ["management"]


def test_bldr_debt_gap_is_a_warning():
    """A3: all-debt-tags-missing must reach data_quality, naming fundamentals."""
    result = buffett.diagnose(BLDR)
    debt = [w for w in result["data_quality"]["warnings"] if w["code"] == "debt_unresolved"]
    assert debt and debt[0]["dimensions_affected"] == ["fundamentals"]
    assert "scored 0 as a data gap" in debt[0]["message"]


def test_bldr_staleness_lag_warned():
    """A4: 2026-03-31 books vs a 2026-07-28 price is a 119-day lag."""
    result = buffett.diagnose(BLDR)
    warnings = result["data_quality"]["warnings"]
    lag = [w for w in warnings if w["code"] == "fundamentals_stale_vs_price"]
    assert lag and lag[0]["context"]["lag_days"] == 119


def test_bldr_trajectory_contradicts_history_score():
    """A5: the block must carry the TTM-NI slide the decade score hides."""
    result = buffett.diagnose(BLDR)
    points = result["recent_trajectory"]["points"]
    assert len(points) == 4
    ni = [p["ttm_net_income"] for p in points]
    assert ni[0] < ni[1] < ni[2] < ni[3]  # most recent first: declining
    assert points[0]["bvps"] < points[1]["bvps"]


def test_bldr_dcf_clamp_disclosed():
    """A7: raw −29% CAGR vs the −3.5% stage-1 clamp must be visible."""
    stages = buffett.diagnose(BLDR)["valuation"]["dcf_stages"]
    assert stages["growth_clamped"] is True
    assert stages["raw_growth_cagr"] < -0.25
    assert stages["stage1_growth"] == pytest.approx(-0.035)


# ---------------------------------------------------------------------------
# unit: stale-window detection and the scoring gate


def test_stale_ttm_fields_parses_window_end_not_stated_lag():
    period = {
        "period_end": "2026-03-31",
        "tags_used": {
            "x_warning": "TTM window ends 2015-12-31, which lags the reference "
            "date 2026-09-30 by 3926 days.",
            "y_warning": "Some quarters were derived from YTD or annual facts.",
        },
    }
    stale = validation.stale_ttm_fields(period)
    # lag vs the period's own end (3743), not the inflated stated 3926
    assert stale == {"x": 3743}


def test_gate_discards_stale_optional_field_without_clean_fallback():
    snapshot = copy.deepcopy(BLDR)
    # remove the annual fallback so policy (b) applies
    for p in snapshot["annual_periods"]:
        p["ttm"]["issuance_or_purchase_of_equity_shares"] = None
    result = buffett.diagnose(snapshot)
    mgmt = result["dimensions"]["management"]
    assert any("Buyback/issuance data absent" in d for d in mgmt["details"])
    assert any("value discarded, dependent checks score 0" in f for f in result["flags"])


def test_gate_retains_stale_mandatory_input_with_flag():
    snapshot = copy.deepcopy(BLDR)
    p0 = snapshot["periods"][0]
    p0["tags_used"]["revenue_warning"] = (
        "TTM window ends 2020-12-31, which lags the reference date."
    )
    # taint the annual fallback too, so no clean substitute exists
    snapshot["annual_periods"][0]["tags_used"]["revenue_warning"] = (
        "TTM window ends 2020-12-31, which lags the reference date."
    )
    result = buffett.diagnose(snapshot)
    assert any("revenue" in f and "stale value retained" in f for f in result["flags"])


# ---------------------------------------------------------------------------
# unit: new validation checks


def _bare_period(end: str) -> dict:
    return {"period_end": end, "ttm": {}, "balance": {}, "tags_used": {}}


def test_fundamentals_staleness_threshold():
    ok = {"fetched_at": "2026-07-28", "periods": [_bare_period("2026-06-30")]}
    assert validation._check_fundamentals_staleness(ok, ("periods",)) == []
    stale = {"fetched_at": "2026-07-28", "periods": [_bare_period("2026-03-31")]}
    found = validation._check_fundamentals_staleness(stale, ("periods",))
    assert found and found[0]["code"] == "fundamentals_stale_vs_price"
    assert found[0]["context"]["lag_days"] == 119


def test_manual_market_cap_warns():
    snap = {"market_cap": 5e9, "market_cap_source": "manual:owner-supplied"}
    found = validation._check_manual_market_cap(snap, ("periods",))
    assert found and found[0]["code"] == "market_cap_manual_unverified"
    derived = {"market_cap": 5e9, "market_cap_source": "derived:cboe.close@..."}
    assert validation._check_manual_market_cap(derived, ("periods",)) == []


def test_debt_one_component_missing_stays_info():
    snapshot = copy.deepcopy(BLDR)
    for arr in ("periods", "annual_periods"):
        for p in snapshot[arr]:
            p["balance"]["short_term_debt"] = 1e8
    findings, _ = validation.run_checks(snapshot)
    assert not any(f["code"] == "debt_unresolved" for f in findings)
    infos = [f for f in findings if f["code"] == "absent_optional_field"]
    assert any(f["context"]["field"] == "long_term_debt" for f in infos)


def test_stale_leg_dropped_finding_from_tags():
    snapshot = copy.deepcopy(BLDR)
    p0 = snapshot["periods"][0]
    p0["tags_used"]["issuance_or_purchase_of_equity_shares_dropped"] = (
        "ProceedsFromIssuanceOfCommonStock: TTM window ends 2015-12-31, "
        "lagging the period end 2026-03-31 by 3743 days (> 185); stale leg "
        "dropped from the combine"
    )
    findings, _ = validation.run_checks(snapshot)
    dropped = [f for f in findings if f["code"] == "stale_leg_dropped"]
    assert dropped and dropped[0]["severity"] == validation.WARN


def test_realign_tags_renames_dropped_keys():
    tags = {
        "share_repurchase": "PaymentsForRepurchaseOfCommonStock",
        "share_issuance_dropped": "ProceedsFromIssuanceOfCommonStock: stale leg dropped",
    }
    _realign_tags(tags)
    assert tags == {
        "issuance_or_purchase_of_equity_shares": "PaymentsForRepurchaseOfCommonStock",
        "issuance_or_purchase_of_equity_shares_dropped": (
            "ProceedsFromIssuanceOfCommonStock: stale leg dropped"
        ),
    }


# ---------------------------------------------------------------------------
# Graham parity (A9) and shared inheritance


def test_graham_inherits_snapshot_warnings():
    result = graham.diagnose(BLDR)
    codes = _warn_codes(result)
    assert "debt_unresolved" in codes
    assert "fundamentals_stale_vs_price" in codes
    for w in result["data_quality"]["warnings"]:
        assert "dimensions_affected" in w


def test_graham_excludes_restated_windows():
    snapshot = copy.deepcopy(load_snapshot("KO"))
    ends = sorted(p["period_end"] for p in snapshot["periods"])
    cutoff = ends[1]  # restate the two oldest windows away
    snapshot.setdefault("validation", {"findings": [], "checks_run": []})
    snapshot["validation"]["findings"].append(
        validation.finding(
            validation.WARN,
            "restatement_402",
            "test: non-reliance",
            filing_date="2026-01-01",
            affected_period_ends=[cutoff],
        )
    )
    snapshot["validation"]["checks_run"] = list(
        snapshot["validation"].get("checks_run", [])
    ) + ["restatement_402"]
    result = graham.diagnose(snapshot)
    assert all(e > cutoff for e in result["provenance"]["periods"])
    assert any(f.startswith("restatement:") for f in result["flags"])


def test_graham_hard_fails_when_restatement_starves_history():
    snapshot = copy.deepcopy(load_snapshot("KO"))
    cutoff = max(p["period_end"] for p in snapshot["periods"])
    snapshot.setdefault("validation", {"findings": [], "checks_run": []})
    snapshot["validation"]["findings"].append(
        validation.finding(
            validation.WARN,
            "restatement_402",
            "test: non-reliance",
            filing_date="2026-01-01",
            affected_period_ends=[cutoff],
        )
    )
    with pytest.raises(MissingDataError):
        graham.diagnose(snapshot)
