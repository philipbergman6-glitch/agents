"""Offline tests for the 13F aggregate/diff/format pipeline (whale_engine.thirteenf).

All fixture rows mimic the real edgartools infotable schema (verified live on
Berkshire's Q1 2026 13F-HR); no network access.
"""

import pandas as pd
import pytest

from whale_engine.thirteenf import (
    PortfolioSnapshot,
    ThirteenFError,
    aggregate_infotable,
    diff_snapshots,
    format_portfolio_markdown,
)

COLS = ["Issuer", "Class", "Cusip", "Value", "PutCall", "SharesPrnAmount", "Ticker"]


def _df(rows):
    return pd.DataFrame(rows, columns=COLS)


def _snap(rows, period="2026-03-31", filed="2026-05-15", accession="acc-cur"):
    return aggregate_infotable(
        _df(rows),
        cik=1067983,
        form="13F-HR",
        filing_date=filed,
        report_period=period,
        accession_no=accession,
    )


CUR_ROWS = [
    # AAPL split across two sub-manager rows -> must aggregate by CUSIP
    ["APPLE INC", "COM", "037833100", 600, "", 60, "AAPL"],
    ["APPLE INC", "COM", "037833100", 400, "", 40, "AAPL"],
    ["COCA COLA CO", "COM", "191216100", 300, "", 30, "KO"],
    # opened this quarter
    ["DELTA AIR LINES INC", "COM NEW", "247361702", 100, "", 10, "DAL"],
    # option row -> excluded from positions and weights
    ["SOME ISSUER", "COM", "999999999", 500, "Put", 50, "XXX"],
]

PRIOR_ROWS = [
    ["APPLE INC", "COM", "037833100", 900, "", 90, "AAPL"],  # trimmed 90 -> 100? no: cur=100
    ["COCA COLA CO", "COM", "191216100", 250, "", 30, "KO"],  # shares unchanged
    ["VISA INC", "COM", "92826C839", 80, "", 8, "V"],  # exited
]


def test_aggregate_sums_by_cusip_and_excludes_options():
    snap = _snap(CUR_ROWS)
    assert set(snap.positions) == {"037833100", "191216100", "247361702"}
    aapl = snap.positions["037833100"]
    assert aapl.shares == 100
    assert aapl.value == 1000
    assert snap.option_rows == 1
    assert snap.total_value == 1400  # option row's 500 not counted


def test_aggregate_hard_fails_on_empty_and_missing_columns():
    with pytest.raises(ThirteenFError, match="empty infotable"):
        _snap([])
    bad = pd.DataFrame([["X", "COM", "1", 1]], columns=["Issuer", "Class", "Cusip", "Value"])
    with pytest.raises(ThirteenFError, match="missing columns"):
        aggregate_infotable(bad, cik=1, form="13F-HR", filing_date="d",
                            report_period="2026-03-31", accession_no="a")


def test_diff_classifies_every_kind():
    cur = _snap(CUR_ROWS)
    prior = _snap(PRIOR_ROWS, period="2025-12-31", filed="2026-02-17", accession="acc-prev")
    kinds = {c.cusip: c.kind for c in diff_snapshots(cur, prior)}
    assert kinds["037833100"] == "added"  # 90 -> 100 shares
    assert kinds["191216100"] == "unchanged"  # 30 -> 30 (value moved, shares didn't)
    assert kinds["247361702"] == "opened"
    assert kinds["92826C839"] == "exited"


def test_format_labels_quarter_lag_and_weights():
    cur = _snap(CUR_ROWS)
    prior = _snap(PRIOR_ROWS, period="2025-12-31", filed="2026-02-17", accession="acc-prev")
    text = format_portfolio_markdown(
        "Berkshire Hathaway", cur, prior,
        extra_notes=["Refresh after Aug 14, 2026."],
    )
    assert "Reporting quarter: Q1 2026 (holdings as of 2026-03-31)" in text
    assert "45-day filing lag" in text
    assert "Refresh after Aug 14, 2026." in text
    # weight = 1000 / 1400, option value excluded from denominator
    assert "71.43%" in text
    # sorted by value: AAPL first
    assert text.index("APPLE INC") < text.index("COCA COLA CO")
    assert "Changes vs Q4 2025" in text
    assert "VISA INC (V) — was 8 shares" in text
    # numbers come only from the filing: total is the exact reported sum
    assert "**$1,400**" in text


def test_format_without_prior_omits_diff():
    cur = _snap(CUR_ROWS)
    text = format_portfolio_markdown("Berkshire Hathaway", cur, None)
    assert "Changes vs" not in text
    assert "QoQ" not in text
