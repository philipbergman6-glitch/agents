"""10-K filings-text moat sidecar (ticket #49, per the #46 decision).

Fetch extracts the latest 10-K's Item 1 (Business — competition /
competitive-strengths discussion) and Item 7 (MD&A) via edgartools item
slicing into a markdown sidecar written next to the snapshot:
``snapshots/<TICKER>-<date>-filings.md``. The snapshot JSON records the
sidecar filename (resolved relative to the snapshot's own directory) plus
the source filing's accession number for provenance.

The sidecar is *cited evidence for narration*, never a scoring input: the
text is verbatim filing prose, whale-agnostic (any scorer's narration may
cite it), and extraction failure must never fail the fetch. Failures are
recorded as WARN findings — dicts of ``{severity, code, message}`` appended
to the snapshot's ``validation`` list (created bare if absent; ticket #48
owns the full data-quality structure and this shape is designed to merge
into it trivially).
"""

from __future__ import annotations

from datetime import date

FORM = "10-K"

# Items extracted, in sidecar order. Risk Factors deliberately excluded
# (boilerplate-heavy; rejected in the #46 decision).
ITEMS: list[tuple[str, str]] = [
    ("Item 1", "Business"),
    ("Item 7", "Management's Discussion and Analysis"),
]

WARN_SEVERITY = "WARN"
WARN_CODE = "filings_sidecar_extraction_failed"

_SIDECAR_SUFFIX = "-filings.md"


def sidecar_filename(ticker: str, fetched_at: str) -> str:
    """Sidecar filename for a snapshot named <TICKER>-<fetched_at>.json."""
    return f"{ticker.upper()}-{fetched_at}{_SIDECAR_SUFFIX}"


def _warn(message: str) -> dict:
    return {"severity": WARN_SEVERITY, "code": WARN_CODE, "message": message}


def _fiscal_year_label(period_of_report: str | None) -> str | None:
    """FY label from the filing's period end, e.g. '2025-09-27' -> 'FY2025'."""
    if not period_of_report:
        return None
    try:
        return f"FY{date.fromisoformat(str(period_of_report)[:10]).year}"
    except ValueError:
        return None


def _render_markdown(ticker: str, meta: dict, items: dict[str, str]) -> str:
    fy = meta.get("fiscal_year") or "unknown fiscal year"
    lines = [
        f"# {ticker} — 10-K filings text ({fy})",
        "",
        f"- Source: SEC EDGAR {meta['form']}, accession {meta['accession_number']}",
        f"- Filed: {meta.get('filing_date') or 'unknown'}; "
        f"period of report: {meta.get('period_of_report') or 'unknown'} ({fy})",
        "- Verbatim item text extracted by whale_engine fetch. Cited evidence "
        "for narration only — never a scoring input; no number here feeds the engine.",
        "",
    ]
    for item, title in ITEMS:
        if item not in items:
            continue
        lines.append(f"## {item}. {title} — {fy}")
        lines.append("")
        lines.append(items[item].strip())
        lines.append("")
    return "\n".join(lines)


def extract_filings_text(company, ticker: str) -> tuple[dict | None, list[dict]]:
    """Extract Item 1 + Item 7 from the latest 10-K.

    Returns ``(sidecar, warnings)``:

    - ``sidecar`` — dict with provenance fields (``accession_number``,
      ``form``, ``filing_date``, ``period_of_report``, ``fiscal_year``,
      ``items``) plus a ``markdown`` key holding the rendered sidecar body
      (the CLI pops ``markdown``, writes the file, and records ``path``).
      ``None`` when nothing could be extracted.
    - ``warnings`` — WARN finding dicts for anything missing (never raises:
      text is enrichment, and extraction failure must not fail the fetch).
    """
    ticker = ticker.upper()
    try:
        filing = company.get_filings(form=FORM).latest(1)
    except Exception as e:
        return None, [_warn(f"{ticker}: could not list {FORM} filings: {e}")]
    if filing is None:
        return None, [_warn(f"{ticker}: no {FORM} filing found on EDGAR")]

    try:
        tenk = filing.obj()
        if tenk is None:
            raise ValueError("filing.obj() returned None")
    except Exception as e:
        return None, [
            _warn(f"{ticker}: could not parse {FORM} {filing.accession_no}: {e}")
        ]

    warnings: list[dict] = []
    items: dict[str, str] = {}
    for item, title in ITEMS:
        try:
            text = tenk[item]
        except Exception as e:
            text = None
            warnings.append(
                _warn(
                    f"{ticker}: failed to slice {item} ({title}) from "
                    f"{FORM} {filing.accession_no}: {e}"
                )
            )
            continue
        if text and str(text).strip():
            items[item] = str(text)
        else:
            warnings.append(
                _warn(
                    f"{ticker}: {item} ({title}) is empty in "
                    f"{FORM} {filing.accession_no}"
                )
            )

    if not items:
        warnings.append(
            _warn(
                f"{ticker}: no items extracted from {FORM} "
                f"{filing.accession_no}; no sidecar written"
            )
        )
        return None, warnings

    period = getattr(tenk, "period_of_report", None) or getattr(
        filing, "period_of_report", None
    )
    meta = {
        "form": FORM,
        "accession_number": str(filing.accession_no),
        "filing_date": str(filing.filing_date) if filing.filing_date else None,
        "period_of_report": str(period) if period else None,
        "fiscal_year": _fiscal_year_label(str(period) if period else None),
        "items": sorted(items),
    }
    meta["markdown"] = _render_markdown(ticker, meta, items)
    return meta, warnings
