# Whale Panel — ubiquitous language

Glossary only. Implementation lives in the scorers and their docstrings; decisions
live in the rubric reviews on the issue tracker.

## Whale

An investor persona with its own versioned **rubric**, scoring one company from one
**snapshot**. Buffett, Graham, Lynch, Greenblatt. A whale may be **diagnosable**
without being a **panel** member.

## Snapshot

Whale-agnostic raw EDGAR data for one ticker, pinned to a file. Fetched once; any
whale diagnoses from the same file. Fields are **additive**: a new whale may add a
field without bumping the schema.

## Rubric

A whale's fixed set of scoring rules, carried as `rubric_version` on every diagnosis.
Changing it requires an owner-signed judgment review. Rubric choices with no
published source are **owner judgment** and are labelled so in the rubric text.

## Walk away

A whale declines to score a company for a **rubric** reason (wrong universe — e.g. a
bank for Greenblatt) and says why. Distinct from a **hard-fail**.

## Hard-fail

The engine refuses to diagnose because a required input is **missing**. Not a score
of zero. Raised as `MissingDataError`; the fix is a refetch or a data correction.

## Degenerate-but-real

An input that is present but makes a ratio meaningless (negative equity, EV ≤ 0,
negative CAGR endpoint). Scores zero on that check with a detail line — the whale
walks away from that check, it does not crash and it does not flag missing data.

## Undefined-by-abundance

Greenblatt only. Tangible capital ≤ 0 with positive EBIT: return on capital has no
meaningful value because the business needs almost no capital. Scores full points and
carries the `asset_light` flag. The opposite of degenerate-but-real.

## Hurdle

Greenblatt's bond comparison: a fixed 6% the after-tax earnings yield must clear
before a signal can be bullish. A constant, never a live rate.

## Gate

A rule that caps or floors the signal regardless of score (Buffett's margin of safety,
Lynch's PEG, Greenblatt's hurdle). A capped signal appends a pinned detail line.

## Signal

bullish / neutral / bearish, from score thresholds plus any **gate**. The panel
counts signals; it never averages scores and never renders a combined verdict.

## Confidence

50–100, distance of the score from the nearest signal boundary, reduced for
WARN-affected dimensions. Not a probability.

## Data quality

WARN findings from the validation layer that ride a diagnosis in `data_quality`,
each mapped to the dimensions it affects. ERROR findings **hard-fail** instead.

## Panel

The set of whales `/panel` runs over one snapshot — a membership list, separate from
the set of diagnosable whales. Joining it is a panel-shape change (`panel_version`).
