"""Deterministic unit tests for Form 4 insider buy-cluster detection (#52).

All tests are pure — synthetic transactions, no network. The cluster rule
under test: >=3 code-P purchases by >=3 distinct insiders within any rolling
90-day window (dates < 90 days apart share a window), 12-month lookback.
"""

import copy
import json
from datetime import date, timedelta

from whale_engine.insider import (
    WARN_CODE_FETCH_FAILED,
    build_insider_activity,
    collect_insider_activity,
    detect_cluster,
)

SNAP_DATE = date(2026, 7, 24)


def txn(insider, d, shares=100.0, value=1000.0, role="Director", accession="acc-1"):
    return {
        "insider": insider,
        "role": role,
        "date": d if isinstance(d, str) else d.isoformat(),
        "shares": shares,
        "value": value,
        "accession_number": accession,
    }


# ---------------------------------------------------------------------------
# detect_cluster


def test_exactly_three_insiders_three_purchases_is_cluster():
    txns = [
        txn("Alice", "2026-01-10"),
        txn("Bob", "2026-02-01"),
        txn("Carol", "2026-03-01"),
    ]
    c = detect_cluster(txns)
    assert c is not None
    assert c["purchases"] == 3
    assert c["distinct_insiders"] == 3
    assert c["insiders"] == ["Alice", "Bob", "Carol"]
    assert c["window_start"] == "2026-01-10"
    assert c["window_end"] == "2026-03-01"
    assert c["total_value"] == 3000.0


def test_same_insider_multiple_buys_is_not_multiple_insiders():
    txns = [
        txn("Alice", "2026-01-10"),
        txn("Alice", "2026-01-20"),
        txn("Alice", "2026-02-01"),
        txn("Bob", "2026-02-05"),
    ]
    assert detect_cluster(txns) is None  # only 2 distinct insiders


def test_two_insiders_many_purchases_is_no_cluster():
    txns = [txn("Alice", f"2026-01-{d:02d}") for d in (5, 10, 15)] + [
        txn("Bob", "2026-01-20")
    ]
    assert detect_cluster(txns) is None


def test_window_boundary_89_days_apart_clusters():
    # First and last 89 days apart: inside one 90-day window (days 0..89).
    txns = [
        txn("Alice", "2026-01-01"),
        txn("Bob", "2026-02-15"),
        txn("Carol", (date(2026, 1, 1) + timedelta(days=89)).isoformat()),
    ]
    assert detect_cluster(txns) is not None


def test_window_boundary_90_days_apart_does_not_cluster():
    # First and last exactly 90 days apart: no single 90-day window holds all 3.
    txns = [
        txn("Alice", "2026-01-01"),
        txn("Bob", "2026-02-15"),
        txn("Carol", (date(2026, 1, 1) + timedelta(days=90)).isoformat()),
    ]
    assert detect_cluster(txns) is None


def test_cluster_found_in_later_window_when_early_buys_are_sparse():
    # Sparse early buys, dense late cluster: detection must slide the window.
    txns = [
        txn("Alice", "2025-09-01"),
        txn("Bob", "2026-03-01"),
        txn("Carol", "2026-03-15"),
        txn("Dave", "2026-04-01"),
    ]
    c = detect_cluster(txns)
    assert c is not None
    assert c["window_start"] == "2026-03-01"
    assert c["purchases"] == 3


def test_fourth_insider_extends_cluster_stats():
    txns = [
        txn("Alice", "2026-01-10", value=500.0),
        txn("Bob", "2026-01-15", value=None),  # missing price -> value None
        txn("Carol", "2026-01-20", value=250.0),
        txn("Dave", "2026-02-01", value=250.0),
    ]
    c = detect_cluster(txns)
    assert c["purchases"] == 4
    assert c["distinct_insiders"] == 4
    assert c["total_value"] == 1000.0  # None values excluded from the sum


def test_all_values_missing_gives_none_total():
    txns = [txn(n, "2026-01-10", value=None) for n in ("Alice", "Bob", "Carol")]
    assert detect_cluster(txns)["total_value"] is None


def test_empty_transactions_no_cluster():
    assert detect_cluster([]) is None


# ---------------------------------------------------------------------------
# build_insider_activity (lookback + section shape)


def test_lookback_excludes_transactions_older_than_12_months():
    # Cluster only forms if the out-of-lookback buy is counted — it must not be.
    old = (SNAP_DATE - timedelta(days=366)).isoformat()
    edge = (SNAP_DATE - timedelta(days=365)).isoformat()
    txns = [
        txn("Alice", old),
        txn("Bob", edge),
        txn("Carol", (SNAP_DATE - timedelta(days=300)).isoformat()),
    ]
    section = build_insider_activity(txns, SNAP_DATE)
    assert section["verdict"] == "no_cluster"
    assert len(section["transactions"]) == 2  # old one dropped
    assert all(t["insider"] != "Alice" for t in section["transactions"])


def test_lookback_boundary_day_365_included():
    edge = (SNAP_DATE - timedelta(days=365)).isoformat()
    txns = [
        txn("Alice", edge),
        txn("Bob", (SNAP_DATE - timedelta(days=340)).isoformat()),
        txn("Carol", (SNAP_DATE - timedelta(days=310)).isoformat()),
    ]
    section = build_insider_activity(txns, SNAP_DATE)
    assert section["verdict"] == "cluster"
    assert section["lookback_start"] == edge


def test_future_dated_transactions_excluded():
    future = (SNAP_DATE + timedelta(days=1)).isoformat()
    txns = [
        txn("Alice", future),
        txn("Bob", "2026-07-01"),
        txn("Carol", "2026-07-02"),
    ]
    section = build_insider_activity(txns, SNAP_DATE)
    assert section["verdict"] == "no_cluster"
    assert len(section["transactions"]) == 2


def test_section_shape_and_verdicts():
    section = build_insider_activity([], SNAP_DATE)
    assert section["verdict"] == "no_cluster"
    assert section["cluster"] is None
    assert section["transactions"] == []
    assert section["lookback_end"] == SNAP_DATE.isoformat()

    clustered = build_insider_activity(
        [txn("Alice", "2026-06-01"), txn("Bob", "2026-06-02"), txn("Carol", "2026-06-03")],
        SNAP_DATE,
    )
    assert clustered["verdict"] == "cluster"
    for t in clustered["transactions"]:
        assert set(t) == {"insider", "role", "date", "shares", "value", "accession_number"}


def test_determinism_input_order_irrelevant():
    txns = [
        txn("Carol", "2026-03-01", accession="acc-3"),
        txn("Alice", "2026-01-10", accession="acc-1"),
        txn("Bob", "2026-02-01", accession="acc-2"),
    ]
    a = build_insider_activity(copy.deepcopy(txns), SNAP_DATE)
    b = build_insider_activity(list(reversed(copy.deepcopy(txns))), SNAP_DATE)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert [t["accession_number"] for t in a["transactions"]] == ["acc-1", "acc-2", "acc-3"]


# ---------------------------------------------------------------------------
# fetch failure -> WARN, never a failed fetch


class _ExplodingCompany:
    def get_filings(self, form=None):
        raise RuntimeError("EDGAR down")


def test_fetch_failure_yields_warn_not_exception():
    section, warning = collect_insider_activity(_ExplodingCompany(), SNAP_DATE)
    assert section is None
    assert warning["severity"] == "WARN"
    assert warning["code"] == WARN_CODE_FETCH_FAILED
    assert "EDGAR down" in warning["message"]


class _EmptyCompany:
    def get_filings(self, form=None):
        return []


def test_no_form4_filings_is_no_cluster_not_warn():
    section, warning = collect_insider_activity(_EmptyCompany(), SNAP_DATE)
    assert warning is None
    assert section["verdict"] == "no_cluster"


# ---------------------------------------------------------------------------
# scorer pass-through (unscored context)


def test_scorers_pass_section_through_unscored():
    from conftest import load_snapshot
    from whale_engine.scorers import buffett as b
    from whale_engine.scorers import graham as g

    snap = load_snapshot("AAPL")
    base_b, base_g = b.diagnose(snap), g.diagnose(snap)
    assert "insider_activity" not in base_b  # old snapshots: key absent
    assert "insider_activity" not in base_g

    snap2 = copy.deepcopy(snap)
    snap2["insider_activity"] = build_insider_activity(
        [txn("Alice", "2026-06-01"), txn("Bob", "2026-06-02"), txn("Carol", "2026-06-03")],
        SNAP_DATE,
    )
    with_b, with_g = b.diagnose(snap2), g.diagnose(snap2)
    assert with_b["insider_activity"] == snap2["insider_activity"]
    assert with_g["insider_activity"] == snap2["insider_activity"]
    # Unscored: everything else identical to the section-free diagnosis.
    with_b.pop("insider_activity"), with_g.pop("insider_activity")
    assert with_b == base_b
    assert with_g == base_g
