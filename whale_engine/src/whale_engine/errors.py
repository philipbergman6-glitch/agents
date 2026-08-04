"""Exceptions shared by every whale's scorer."""

from __future__ import annotations


class MissingDataError(ValueError):
    """A valuation-critical input is absent. Hard fail; never score around it."""


class FetchError(RuntimeError):
    """A networked fetch could not produce usable data. Hard fail, no fallback.

    Base for every fetch path so one `except FetchError` catches them all —
    EDGAR (fetch.FetchError) and Alpha Vantage price history
    (prices.PriceFetchError) alike.
    """
