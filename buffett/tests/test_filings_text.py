"""Filings-text moat sidecar (ticket #49): extraction, failure paths, CLI wiring.

Offline: edgartools objects are faked with the minimal surface the extractor
touches (Company.get_filings(...).latest(1) -> Filing.obj() -> TenK["Item N"]).
"""

import json

from whale_engine.filings_text import (
    WARN_CODE,
    extract_filings_text,
    sidecar_filename,
)

ITEM1_TEXT = "We compete on brand strength and switching costs. Our moat is wide."
ITEM7_TEXT = "Management's discussion: pricing actions offset input-cost inflation."


class FakeTenK:
    def __init__(self, items, period_of_report="2025-09-27"):
        self._items = items
        self.period_of_report = period_of_report

    def __getitem__(self, item):
        try:
            return self._items[item]
        except KeyError:
            raise KeyError(item)


class FakeFiling:
    accession_no = "0000320193-25-000123"
    filing_date = "2025-10-31"
    period_of_report = "2025-09-27"

    def __init__(self, tenk):
        self._tenk = tenk

    def obj(self):
        if isinstance(self._tenk, Exception):
            raise self._tenk
        return self._tenk


class FakeFilings:
    def __init__(self, filing):
        self._filing = filing

    def latest(self, n=1):
        return self._filing


class FakeCompany:
    def __init__(self, filing):
        self._filing = filing

    def get_filings(self, form=None):
        assert form == "10-K"
        return FakeFilings(self._filing)


def test_both_items_extracted():
    company = FakeCompany(
        FakeFiling(FakeTenK({"Item 1": ITEM1_TEXT, "Item 7": ITEM7_TEXT}))
    )
    sidecar, warnings = extract_filings_text(company, "aapl")
    assert warnings == []
    assert sidecar is not None
    assert sidecar["accession_number"] == "0000320193-25-000123"
    assert sidecar["form"] == "10-K"
    assert sidecar["fiscal_year"] == "FY2025"
    assert sidecar["items"] == ["Item 1", "Item 7"]
    md = sidecar["markdown"]
    assert ITEM1_TEXT in md
    assert ITEM7_TEXT in md
    assert "## Item 1. Business — FY2025" in md
    assert "## Item 7. Management's Discussion and Analysis — FY2025" in md
    assert "0000320193-25-000123" in md
    # Ticker normalized to upper case.
    assert md.startswith("# AAPL")


def test_partial_extraction_keeps_sidecar_and_warns():
    company = FakeCompany(FakeFiling(FakeTenK({"Item 1": ITEM1_TEXT})))
    sidecar, warnings = extract_filings_text(company, "AAPL")
    assert sidecar is not None
    assert sidecar["items"] == ["Item 1"]
    assert "Item 7" not in sidecar["markdown"]
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "WARN"
    assert warnings[0]["code"] == WARN_CODE
    assert "Item 7" in warnings[0]["message"]


def test_empty_item_text_warns():
    company = FakeCompany(
        FakeFiling(FakeTenK({"Item 1": "   ", "Item 7": ITEM7_TEXT}))
    )
    sidecar, warnings = extract_filings_text(company, "AAPL")
    assert sidecar is not None
    assert sidecar["items"] == ["Item 7"]
    assert len(warnings) == 1
    assert "Item 1" in warnings[0]["message"]


def test_no_items_extracted_returns_none_with_warnings():
    company = FakeCompany(FakeFiling(FakeTenK({})))
    sidecar, warnings = extract_filings_text(company, "AAPL")
    assert sidecar is None
    assert warnings  # per-item warnings + terminal "no sidecar written"
    assert all(w["severity"] == "WARN" and w["code"] == WARN_CODE for w in warnings)
    assert "no sidecar written" in warnings[-1]["message"]


def test_no_tenk_filing_returns_warn_not_raise():
    company = FakeCompany(None)  # latest(1) -> None
    sidecar, warnings = extract_filings_text(company, "AAPL")
    assert sidecar is None
    assert len(warnings) == 1
    assert warnings[0]["code"] == WARN_CODE
    assert "no 10-K filing" in warnings[0]["message"]


def test_unparseable_filing_returns_warn_not_raise():
    company = FakeCompany(FakeFiling(RuntimeError("boom: malformed document")))
    sidecar, warnings = extract_filings_text(company, "AAPL")
    assert sidecar is None
    assert len(warnings) == 1
    assert "boom: malformed document" in warnings[0]["message"]


def test_get_filings_exception_returns_warn_not_raise():
    class ExplodingCompany:
        def get_filings(self, form=None):
            raise ConnectionError("EDGAR down")

    sidecar, warnings = extract_filings_text(ExplodingCompany(), "AAPL")
    assert sidecar is None
    assert len(warnings) == 1
    assert "EDGAR down" in warnings[0]["message"]


def test_missing_period_of_report_still_extracts():
    tenk = FakeTenK({"Item 1": ITEM1_TEXT}, period_of_report=None)
    filing = FakeFiling(tenk)
    filing.period_of_report = None
    company = FakeCompany(filing)
    sidecar, warnings = extract_filings_text(company, "AAPL")
    assert sidecar is not None
    assert sidecar["fiscal_year"] is None
    assert "unknown fiscal year" in sidecar["markdown"]


def test_sidecar_filename():
    assert sidecar_filename("aapl", "2026-07-28") == "AAPL-2026-07-28-filings.md"


# --- CLI wiring: sidecar written next to the snapshot, path + warnings recorded


def _fake_snapshot(with_sidecar: bool, with_warning: bool) -> dict:
    snap = {
        "schema_version": 1,
        "ticker": "AAPL",
        "fetched_at": "2026-07-28",
        "market_cap": 1.0,
        "market_cap_source": "test",
        "source": {},
        "periods": [],
    }
    if with_sidecar:
        snap["filings_sidecar"] = {
            "form": "10-K",
            "accession_number": "0000320193-25-000123",
            "filing_date": "2025-10-31",
            "period_of_report": "2025-09-27",
            "fiscal_year": "FY2025",
            "items": ["Item 1", "Item 7"],
            "markdown": "# AAPL — 10-K filings text (FY2025)\n\nbody\n",
        }
    if with_warning:
        snap["validation"] = [
            {"severity": "WARN", "code": WARN_CODE, "message": "Item 7 missing"}
        ]
    return snap


def test_cli_fetch_writes_sidecar_and_records_path(tmp_path, monkeypatch, capsys):
    from whale_engine import cli

    monkeypatch.setattr(
        "whale_engine.fetch.fetch_snapshot",
        lambda ticker, today=None, **kwargs: _fake_snapshot(True, False),
    )
    rc = cli.main(["fetch", "AAPL", "--snapshots-dir", str(tmp_path)])
    assert rc == 0
    snap_path = tmp_path / "AAPL-2026-07-28.json"
    sidecar_path = tmp_path / "AAPL-2026-07-28-filings.md"
    assert capsys.readouterr().out.strip() == str(snap_path)
    assert sidecar_path.read_text() == "# AAPL — 10-K filings text (FY2025)\n\nbody\n"
    snap = json.loads(snap_path.read_text())
    sidecar = snap["filings_sidecar"]
    assert sidecar["path"] == "AAPL-2026-07-28-filings.md"
    assert sidecar["accession_number"] == "0000320193-25-000123"
    assert "markdown" not in sidecar  # transient key never lands in the JSON


def test_cli_fetch_without_sidecar_still_succeeds(tmp_path, monkeypatch):
    from whale_engine import cli

    monkeypatch.setattr(
        "whale_engine.fetch.fetch_snapshot",
        lambda ticker, today=None, **kwargs: _fake_snapshot(False, True),
    )
    rc = cli.main(["fetch", "AAPL", "--snapshots-dir", str(tmp_path)])
    assert rc == 0
    snap = json.loads((tmp_path / "AAPL-2026-07-28.json").read_text())
    assert "filings_sidecar" not in snap
    assert snap["validation"][0]["code"] == WARN_CODE
    assert not list(tmp_path.glob("*-filings.md"))
