"""Exceptions shared by every whale's scorer."""

from __future__ import annotations


class MissingDataError(ValueError):
    """A valuation-critical input is absent. Hard fail; never score around it."""
