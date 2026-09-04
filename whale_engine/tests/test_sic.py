"""Additive SIC fields on the EDGAR snapshot (per methodology v1).

The portfolio layer groups a basket by 2-digit SIC major group; the source is
the EDGAR submissions API (already behind edgartools' Company.sic /
Company.industry), never a new vendor. Additive: absence is a WARN, never a
failed fetch, and no scorer reads these fields.
"""

import pytest

import whale_engine.fetch as fetch


class FakeCompany:
    def __init__(self, sic=None, industry=None, raises=False):
        self._sic, self._industry, self._raises = sic, industry, raises

    @property
    def sic(self):
        if self._raises:
            raise RuntimeError("submissions unavailable")
        return self._sic

    @property
    def industry(self):
        if self._raises:
            raise RuntimeError("submissions unavailable")
        return self._industry


def test_sic_is_read_from_submissions_and_normalized_to_a_string():
    sic, desc, warning = fetch._company_sic(FakeCompany(7372, "Prepackaged Software"))
    assert sic == "7372"
    assert desc == "Prepackaged Software"
    assert warning is None


def test_zero_padded_sic_survives_as_filed():
    sic, desc, warning = fetch._company_sic(FakeCompany("0700", "Agricultural Services"))
    assert sic == "0700"
    assert warning is None


def test_missing_sic_warns_and_never_fails_the_fetch():
    sic, desc, warning = fetch._company_sic(FakeCompany(None, None))
    assert sic is None and desc is None
    assert warning["severity"] == "WARN"
    assert warning["code"] == "sic_unavailable"


def test_submissions_failure_warns_and_never_fails_the_fetch():
    sic, desc, warning = fetch._company_sic(FakeCompany(raises=True))
    assert sic is None and desc is None
    assert warning["code"] == "sic_unavailable"


def test_sic_warning_is_carried_forward_by_diagnoses():
    from whale_engine import validation

    assert "sic_unavailable" in validation.FETCH_ONLY_CODES


@pytest.mark.parametrize("bad", ["", "   ", "n/a"])
def test_unusable_sic_text_warns(bad):
    sic, desc, warning = fetch._company_sic(FakeCompany(bad, "Something"))
    assert sic is None
    assert warning["code"] == "sic_unavailable"
