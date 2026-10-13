"""Additive net-fixed-assets balance field (Greenblatt rubric v1, #109).

Additive per the SIC precedent: no schema_version bump, no new validation
finding (absence is Greenblatt's hard-fail, never a WARN the other whales
would inherit). Resolution is freshest-across-tags — a fixed tag order goes
stale in both directions on real filers (F +20%, HUT -44%, #116).
"""

from datetime import date

import pandas as pd

import whale_engine.fetch as fetch

PPEN = "PropertyPlantAndEquipmentNet"
PPE_ROU = (
    "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfter"
    "AccumulatedDepreciationAndAmortization"
)
GROSS = "PropertyPlantAndEquipmentGross"
ACCUM = "AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment"


def _history(rows):
    """rows: [(period_end, value, filing_date)] as instants."""
    return pd.DataFrame(
        {
            "period_type": "instant",
            "period_end": [r[0] for r in rows],
            "numeric_value": [r[1] for r in rows],
            "filing_date": [r[2] for r in rows],
        }
    )


def _empty_balance_histories():
    return {field: [] for field in fetch.BALANCE_TAGS}


def _build(nfa_histories, window_end=date(2026, 6, 30)):
    balance, tags_used = fetch._build_balance(
        window_end,
        _empty_balance_histories(),
        [(fetch.ST_DEBT_PRIMARY, None)],
        None,
        None,
        nfa_histories,
    )
    return balance, tags_used


def test_plain_net_tag_resolves_with_provenance():
    hist = {PPEN: _history([("2026-06-30", 2_046_000_000.0, "2026-08-01")])}
    balance, tags_used = _build(hist)
    assert balance["net_fixed_assets"] == 2_046_000_000.0
    assert tags_used["net_fixed_assets"] == f"{PPEN}@2026-06-30"


def test_fresher_rou_combined_tag_beats_stale_plain_tag():
    # F FY2025: plain PPEN last filed at 2025-09-30 (44.7B), the ROU-combined
    # tag at the period end itself (37.3B). First-wins would be +20% high.
    hist = {
        PPEN: _history([("2025-09-30", 44_735_000_000.0, "2025-10-28")]),
        PPE_ROU: _history([("2025-12-31", 37_288_000_000.0, "2026-02-10")]),
    }
    balance, tags_used = _build(hist, window_end=date(2025, 12, 31))
    assert balance["net_fixed_assets"] == 37_288_000_000.0
    assert tags_used["net_fixed_assets"] == f"{PPE_ROU}@2025-12-31"


def test_stale_rou_tag_loses_to_fresher_plain_tag():
    # MA 2026-03-31: ROU-combined filed only at year end, plain tag at quarter.
    hist = {
        PPEN: _history([("2026-03-31", 2_349_000_000.0, "2026-04-30")]),
        PPE_ROU: _history([("2025-12-31", 2_303_000_000.0, "2026-02-12")]),
    }
    balance, tags_used = _build(hist, window_end=date(2026, 3, 31))
    assert balance["net_fixed_assets"] == 2_349_000_000.0
    assert tags_used["net_fixed_assets"] == f"{PPEN}@2026-03-31"


def test_date_tie_goes_to_the_plain_net_tag():
    hist = {
        PPEN: _history([("2026-06-30", 100.0, "2026-08-01")]),
        PPE_ROU: _history([("2026-06-30", 120.0, "2026-08-01")]),
    }
    balance, tags_used = _build(hist)
    assert balance["net_fixed_assets"] == 100.0
    assert tags_used["net_fixed_assets"] == f"{PPEN}@2026-06-30"


def test_no_tag_resolves_leaves_field_none_without_provenance():
    balance, tags_used = _build({})
    assert balance["net_fixed_assets"] is None
    assert "net_fixed_assets" not in tags_used


def test_derived_gross_minus_accumulated_is_last_resort_and_flagged():
    # IREN after 2025-09-30 files only the gross and accumulated legs.
    hist = {
        GROSS: _history([("2026-03-31", 5_000_000_000.0, "2026-05-01")]),
        ACCUM: _history([("2026-03-31", 459_000_000.0, "2026-05-01")]),
    }
    balance, tags_used = _build(hist, window_end=date(2026, 3, 31))
    assert balance["net_fixed_assets"] == 5_000_000_000.0 - 459_000_000.0
    assert tags_used["net_fixed_assets"] == f"derived:{GROSS}-{ACCUM}@2026-03-31"
    assert "derived" in tags_used["net_fixed_assets_derived"]


def test_derived_legs_must_share_a_period_end():
    hist = {
        GROSS: _history([("2026-03-31", 5_000_000_000.0, "2026-05-01")]),
        ACCUM: _history([("2025-12-31", 420_000_000.0, "2026-02-01")]),
    }
    balance, tags_used = _build(hist, window_end=date(2026, 3, 31))
    assert balance["net_fixed_assets"] is None
    assert "net_fixed_assets" not in tags_used


def test_fresher_derivation_beats_a_stale_filed_tag():
    # IREN 2025-12-31: plain PPEN last filed a quarter earlier; only the gross
    # and accumulated legs are at the period end (#116: -34% if PPEN won).
    hist = {
        PPEN: _history([("2025-09-30", 2_115_000_000.0, "2025-11-01")]),
        GROSS: _history([("2025-12-31", 3_600_000_000.0, "2026-02-01")]),
        ACCUM: _history([("2025-12-31", 393_000_000.0, "2026-02-01")]),
    }
    balance, tags_used = _build(hist, window_end=date(2025, 12, 31))
    assert balance["net_fixed_assets"] == 3_600_000_000.0 - 393_000_000.0
    assert tags_used["net_fixed_assets"] == f"derived:{GROSS}-{ACCUM}@2025-12-31"


def test_filed_tag_beats_derivation_on_a_date_tie():
    hist = {
        PPE_ROU: _history([("2026-03-31", 3_207_000_000.0, "2026-05-01")]),
        GROSS: _history([("2026-03-31", 3_600_000_000.0, "2026-05-01")]),
        ACCUM: _history([("2026-03-31", 393_000_000.0, "2026-05-01")]),
    }
    balance, tags_used = _build(hist, window_end=date(2026, 3, 31))
    assert balance["net_fixed_assets"] == 3_207_000_000.0
    assert tags_used["net_fixed_assets"] == f"{PPE_ROU}@2026-03-31"
    assert "net_fixed_assets_derived" not in tags_used
