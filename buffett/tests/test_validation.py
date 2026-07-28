"""Validation layer (ticket #48, per the #44 decision).

Covers the seven checks, the finding shape (mergeable list of plain dicts),
the diagnosis `data_quality` block, and the hard-fail-on-ERROR contract, using
the committed audit snapshots (JPM = bank, CAVA = pre-IPO quirks, NVDA = two
splits) plus synthetic mutations.
"""

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from whale_engine import validation
from whale_engine.errors import MissingDataError
from whale_engine.fetch import _attach_validation, _check_restatements, _realign_tags
from whale_engine.scorers import buffett, graham

from conftest import SNAPSHOTS, load_snapshot


def load_snapshot_dated(ticker: str, day: str) -> dict:
    return json.loads((SNAPSHOTS / f"{ticker}-{day}.json").read_text())


# ---------------------------------------------------------------------------
# finding shape & data_quality block


def test_findings_are_plain_mergeable_dicts():
    findings, checks_run = validation.run_checks(load_snapshot("KO"))
    assert findings, "audit snapshots always carry at least the stitched-TTM WARN"
    for f in findings:
        assert set(f) == {"severity", "code", "message", "context"}
        assert f["severity"] in (validation.ERROR, validation.WARN, validation.INFO)
        assert isinstance(f["context"], dict)
    assert isinstance(checks_run, list) and len(checks_run) == 6  # no restatement stored


def test_data_quality_block_shape_and_info_excluded():
    result = buffett.diagnose(load_snapshot("KO"))
    dq = result["data_quality"]
    assert set(dq) == {"errors", "warnings", "checks_run"}
    assert dq["errors"] == []  # ERRORs raise; a successful diagnosis has none
    assert dq["warnings"], "stitched-TTM warnings must surface in the diagnosis"
    assert all(f["severity"] == "WARN" for f in dq["warnings"])
    # INFO findings are snapshot-level only (per #44), never in data_quality.
    assert not any(f["severity"] == "INFO" for f in dq["warnings"] + dq["errors"])


def test_parallel_features_can_append_findings():
    """Tickets #49/#50/#52 merge by appending finding dicts — nothing else."""
    dq = validation.data_quality(
        [validation.finding(validation.WARN, "someone_elses_check", "hi", extra=1)],
        ["someone_elses_check"],
    )
    assert dq["warnings"][0]["code"] == "someone_elses_check"


# ---------------------------------------------------------------------------
# check 1: stitched-TTM warnings surface for all fields


def test_ttm_warnings_surface_in_both_whales():
    snapshot = load_snapshot("CAVA")
    for mod in (buffett, graham):
        warnings = mod.diagnose(snapshot)["data_quality"]["warnings"]
        assert any(f["code"] == "ttm_stitched" for f in warnings)


def test_ttm_warning_capture_is_not_net_income_only():
    """A warning recorded against any field must produce its own finding."""
    snapshot = copy.deepcopy(load_snapshot("KO"))
    snapshot["periods"][0]["tags_used"]["revenue_warning"] = "gaps in revenue"
    findings, _ = validation.run_checks(snapshot)
    stitched = [f for f in findings if f["code"] == "ttm_stitched"]
    assert any(f["context"]["field"] == "revenue" for f in stitched)


# ---------------------------------------------------------------------------
# check 2: market-cap order-of-magnitude bounds


@pytest.mark.parametrize("bad_cap", [1e3, 1e20, -5.0])
def test_market_cap_out_of_bounds_hard_fails(bad_cap):
    snapshot = copy.deepcopy(load_snapshot("KO"))
    snapshot["market_cap"] = bad_cap
    with pytest.raises(MissingDataError, match="validation failed"):
        buffett.diagnose(snapshot)


def test_market_cap_in_bounds_passes():
    findings, _ = validation.run_checks(load_snapshot("KO"))
    assert not any(f["code"] == "market_cap_bounds" for f in findings)


def test_market_cap_matching_price_reference_passes():
    snapshot = copy.deepcopy(load_snapshot("KO"))
    shares = 4_000_000_000.0
    snapshot["price_reference"] = {"price": 60.0, "shares": shares}
    snapshot["market_cap"] = 60.0 * shares * 1.05  # within 10%
    findings, _ = validation.run_checks(snapshot)
    assert not any(
        f["code"] == "market_cap_reference_mismatch" for f in findings
    )


def test_market_cap_deviating_from_price_reference_hard_fails():
    snapshot = copy.deepcopy(load_snapshot("KO"))
    shares = 4_000_000_000.0
    snapshot["price_reference"] = {"price": 60.0, "shares": shares}
    snapshot["market_cap"] = 60.0 * shares * 1.25  # 25% off its own derivation
    findings, _ = validation.run_checks(snapshot)
    assert any(
        f["code"] == "market_cap_reference_mismatch"
        and f["severity"] == validation.ERROR
        for f in findings
    )
    with pytest.raises(MissingDataError, match="validation failed"):
        buffett.diagnose(snapshot)


# ---------------------------------------------------------------------------
# check 3: split-aware renormalization (unit level; scorer level lives in
# test_score_units / test_graham_units)


def test_renormalize_nvda_annual_shape():
    """Two real splits: the whole decade lands on the current share basis."""
    entries = [
        ("2026-01-25", 24.304e9), ("2025-01-26", 24.477e9), ("2024-01-28", 24.643e9),
        ("2023-01-29", 2.466e9), ("2022-01-30", 2.506e9), ("2021-01-31", 2.479e9),
        ("2020-01-26", 0.612e9), ("2019-01-27", 0.606e9), ("2018-01-28", 0.606e9),
        ("2017-01-29", 0.585e9),
    ]
    adjusted, events = validation.renormalize_share_series(entries)
    assert [e["type"] for e in events] == ["split", "split"]
    assert [e["factor"] for e in events] == [10.0, 4.0]  # per-boundary steps
    assert all(a is not None for a in adjusted)
    assert adjusted[3] == pytest.approx(24.66e9)  # 2.466e9 * 10
    assert adjusted[9] == pytest.approx(23.4e9)   # 0.585e9 * 40


def test_renormalize_unexplained_jump_excludes_older_segment():
    entries = [("2024-01-01", 113.7e6), ("2023-01-01", 1.4e6), ("2022-01-01", 1.3e6)]
    adjusted, events = validation.renormalize_share_series(entries)
    assert events[0]["type"] == "unexplained"
    assert events[0]["excluded_period_ends"] == ["2023-01-01", "2022-01-01"]
    assert adjusted == [113.7e6, None, None]


def test_renormalize_stale_middle_period_is_a_repair():
    entries = [("2024-10-01", 24.0e9), ("2024-07-01", 2.4e9), ("2024-04-01", 24.0e9)]
    adjusted, events = validation.renormalize_share_series(entries)
    assert [e["type"] for e in events] == ["repair"]
    assert events[0]["period_end"] == "2024-07-01"
    assert adjusted == [24.0e9, pytest.approx(24.0e9), pytest.approx(24.0e9)]


def test_renormalize_dilution_below_threshold_untouched():
    entries = [("2021-01-01", 650.0), ("2020-01-01", 448.0)]  # AAL x1.45
    adjusted, events = validation.renormalize_share_series(entries)
    assert events == []
    assert adjusted == [650.0, 448.0]


def test_nvda_book_value_history_restored():
    """The audit's headline scoring bug (b-2): the outlier filter kept 3 of 10
    fiscal years for NVDA BVPS. Renormalization must keep all 10."""
    snapshot = load_snapshot("NVDA")
    result = buffett.diagnose(snapshot)
    assert not any("excluded" in f for f in result["flags"] if "book_value" in f)
    renorm = [f for f in result["flags"] if "renormalized" in f]
    assert len(renorm) == 2 and any("x10" in f for f in renorm) and any(
        "x4" in f for f in renorm
    )


# ---------------------------------------------------------------------------
# check 4: financial-sector applicability guard


def test_bank_fails_with_sector_message_not_missing_tags():
    jpm = load_snapshot_dated("JPM", "2026-07-28")
    for mod in (buffett, graham):
        with pytest.raises(MissingDataError, match="financial-sector"):
            mod.diagnose(jpm)


def test_sector_guard_needs_all_markers_absent():
    findings, _ = validation.run_checks(load_snapshot("KO"))
    assert not any(f["code"] == "sector_applicability" for f in findings)


# ---------------------------------------------------------------------------
# check 5: tags_used alignment + zero-vs-missing marker (INFO, snapshot-level)


def test_pre_alignment_snapshot_reports_unattributed_fields():
    findings, _ = validation.run_checks(load_snapshot("KO"))
    misaligned = {f["context"]["field"] for f in findings if f["code"] == "tags_used_misaligned"}
    # Committed snapshots predate the fetch-side key realignment.
    assert "dividends_and_other_cash_distributions" in misaligned
    assert "issuance_or_purchase_of_equity_shares" in misaligned


def test_realign_tags_closes_the_join_gap():
    tags = {
        "dividends_paid": "PaymentsOfDividends",
        "share_issuance": "ProceedsFromIssuanceOfCommonStock",
        "share_repurchase": "PaymentsForRepurchaseOfCommonStock",
        "net_income": "NetIncomeLoss",
        "net_income_warning": "stitched",
    }
    _realign_tags(tags)
    assert tags == {
        "dividends_and_other_cash_distributions": "PaymentsOfDividends",
        "issuance_or_purchase_of_equity_shares": (
            "ProceedsFromIssuanceOfCommonStock+PaymentsForRepurchaseOfCommonStock"
        ),
        "net_income": "NetIncomeLoss",
        "net_income_warning": "stitched",
    }


def test_zero_vs_missing_marker_for_debt_free_filer():
    """CAVA files no dividend/buyback/debt tags: the ambiguity is recorded."""
    findings, _ = validation.run_checks(load_snapshot("CAVA"))
    marked = {f["context"]["field"] for f in findings if f["code"] == "absent_optional_field"}
    assert "dividends_and_other_cash_distributions" in marked
    assert all(
        f["severity"] == "INFO" for f in findings if f["code"] == "absent_optional_field"
    )


# ---------------------------------------------------------------------------
# check 6: invariants


def test_sign_convention_violation_hard_fails():
    snapshot = copy.deepcopy(load_snapshot("KO"))
    snapshot["periods"][0]["ttm"]["capital_expenditure"] = 1.0e9  # positive = corrupt
    with pytest.raises(MissingDataError, match="sign"):
        buffett.diagnose(snapshot)


def test_balance_identity_isolated_old_period_warns_not_fails():
    """CAVA pre-IPO: mezzanine preferred sits in neither Liabilities nor
    StockholdersEquity (gap 113%) — degraded history, not an invalid snapshot."""
    result = buffett.diagnose(load_snapshot("CAVA"))
    idents = [f for f in result["data_quality"]["warnings"] if f["code"] == "balance_identity"]
    assert idents and all(f["severity"] == "WARN" for f in idents)


def test_balance_identity_latest_period_violation_hard_fails():
    snapshot = copy.deepcopy(load_snapshot("KO"))
    snapshot["periods"][0]["balance"]["total_assets"] *= 3.0
    with pytest.raises(MissingDataError, match="liabilities"):
        buffett.diagnose(snapshot)


# ---------------------------------------------------------------------------
# check 7: 8-K Item 4.02 restatement guard


class _StubFiling:
    def __init__(self, filing_date, items):
        self.filing_date = filing_date
        self.items = items


class _StubCompany:
    def __init__(self, filings):
        self._filings = filings

    def get_filings(self, form):
        assert form == "8-K"
        return self._filings


ANNUALS = [{"period_end": f"{y}-12-31"} for y in range(2016, 2026)]


def test_restatement_402_names_affected_years():
    company = _StubCompany(
        [
            _StubFiling(date(2023, 6, 1), ["2.02", "9.01"]),  # routine 8-K
            _StubFiling(date(2024, 3, 15), ["4.02"]),
        ]
    )
    findings = _check_restatements(company, ANNUALS, today=date(2026, 7, 28))
    assert len(findings) == 1
    f = findings[0]
    assert f["code"] == "restatement_402" and f["severity"] == "WARN"
    # 3-year conservative lookback from the 2024-03-15 filing.
    assert sorted(f["context"]["affected_period_ends"]) == [
        "2021-12-31", "2022-12-31", "2023-12-31"
    ]


def test_restatement_outside_ten_year_window_ignored():
    company = _StubCompany([_StubFiling(date(2014, 1, 1), ["4.02"])])
    assert _check_restatements(company, ANNUALS, today=date(2026, 7, 28)) == []


def test_restatement_metadata_failure_is_an_explicit_warn():
    class _Broken:
        def get_filings(self, form):
            raise RuntimeError("edgartools drift")

    findings = _check_restatements(_Broken(), ANNUALS, today=date(2026, 7, 28))
    assert [f["code"] for f in findings] == ["restatement_guard_unavailable"]


def test_diagnose_excludes_restated_years_from_history():
    snapshot = copy.deepcopy(load_snapshot("KO"))
    affected = [p["period_end"] for p in snapshot["annual_periods"][:2]]
    snapshot["validation"] = {
        "findings": [
            validation.finding(
                validation.WARN,
                "restatement_402",
                "8-K Item 4.02 filed",
                filing_date="2026-05-01",
                affected_period_ends=affected,
            )
        ],
        "checks_run": ["restatement_402"],
    }
    result = buffett.diagnose(snapshot)
    for end in affected:
        assert end not in result["provenance"]["annual_periods"]
    assert any("restatement" in f for f in result["flags"])
    assert any(
        f["code"] == "restatement_402" for f in result["data_quality"]["warnings"]
    )
    assert "restatement_402" in result["data_quality"]["checks_run"]


def test_diagnose_hard_fails_if_restatement_guts_history():
    snapshot = copy.deepcopy(load_snapshot("KO"))
    affected = [p["period_end"] for p in snapshot["annual_periods"][:8]]
    snapshot["validation"] = {
        "findings": [
            validation.finding(
                validation.WARN,
                "restatement_402",
                "8-K Item 4.02 filed",
                affected_period_ends=affected,
            )
        ],
        "checks_run": ["restatement_402"],
    }
    with pytest.raises(MissingDataError, match="restated"):
        buffett.diagnose(snapshot)


def test_attach_validation_writes_snapshot_section():
    """Fetch-time tail: pure findings + restatement guard land in the
    snapshot's validation section, and diagnose carries the guard forward."""
    snapshot = copy.deepcopy(load_snapshot("KO"))
    fy_end = snapshot["annual_periods"][1]["period_end"]
    company = _StubCompany([_StubFiling(date(2026, 1, 15), ["4.02"])])
    _attach_validation(snapshot, company, today=date(2026, 7, 27))
    section = snapshot["validation"]
    assert "restatement_402" in section["checks_run"]
    codes = {f["code"] for f in section["findings"]}
    assert "restatement_402" in codes and "ttm_stitched" in codes
    result = buffett.diagnose(snapshot)
    assert fy_end not in result["provenance"]["annual_periods"]


def test_attach_validation_guard_failure_is_explicit():
    class _Broken:
        def get_filings(self, form):
            raise RuntimeError("no items metadata")

    snapshot = copy.deepcopy(load_snapshot("KO"))
    _attach_validation(snapshot, _Broken(), today=date(2026, 7, 27))
    section = snapshot["validation"]
    assert "restatement_402" not in section["checks_run"]
    assert any(
        f["code"] == "restatement_guard_unavailable" for f in section["findings"]
    )
    # The unavailability WARN must survive into the diagnosis.
    result = buffett.diagnose(snapshot)
    assert any(
        f["code"] == "restatement_guard_unavailable"
        for f in result["data_quality"]["warnings"]
    )


# ---------------------------------------------------------------------------
# graham inheritance contract


def test_graham_data_quality_ignores_annual_only_findings():
    """Graham checks the quarterly array only, so a defect injected into
    annual_periods must not leak into its data_quality block."""
    snapshot = copy.deepcopy(load_snapshot("KO"))
    snapshot["annual_periods"][5]["ttm"]["capital_expenditure"] = 1.0e9
    graham.diagnose(snapshot)  # buffett would hard-fail on the sign violation
    with pytest.raises(MissingDataError):
        buffett.diagnose(snapshot)
