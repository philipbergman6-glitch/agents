# Whale Panel — deterministic investor-persona diagnosis engine with LLM narration

[![CI](https://github.com/philipbergman6-glitch/agents/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/philipbergman6-glitch/agents/actions/workflows/ci.yml)

Ask "what would Buffett, Graham or Lynch say about this stock?" without letting
a language model touch a number. A plain-Python engine pulls a company's SEC
filings, pins them to a snapshot, and scores that snapshot under a versioned
per-investor rubric — same file in, byte-identical JSON out. Claude Code
subagents then narrate the JSON in each investor's voice, and are contractually
forbidden from computing, estimating or rounding beyond presentation. The
`/panel` skill runs all three in parallel and reports where they agree and
disagree; it never averages them, because three philosophies with different
models of value are not a vote. The engineering point is the seam: **the engine
computes, the LLM narrates, and the panel never averages** — and the test
suite checks the narrations against the numbers.

## What it looks like

`uv run whale diagnose KO --whale buffett --snapshot snapshots/KO-2026-08-04.json`
(committed snapshot, offline, deterministic — excerpt):

```json
{
  "ticker": "KO",
  "rubric_version": 3,
  "signal": "bearish",
  "confidence": 55,
  "confidence_detail": {"base": 70, "data_quality_penalty": 15,
                        "affected_dimensions": ["fundamentals", "management", "valuation"]},
  "score": {"total": 16, "max": 27, "max_possible": 27, "pct": 0.5926},
  "dimensions": {
    "moat": {"score": 3, "max": 5, "details": [
      "ROE > 15% in 9/10 periods (avg 36.8%) ✓ (+2)",
      "Operating margins avg 25.0% (recent 3y 24.9% vs prior 3y 26.4%) ✗ (+0)",
      "Asset turnover never above 1.0 ✗ (+0)",
      "Performance stability 79.8% > 70% ✓ (+1)"]}
  },
  "valuation": {"owner_earnings": 14740350000.0, "intrinsic_value": 193960263457.88647,
                "market_cap": 373713622827.48, "margin_of_safety": -0.481,
                "dcf_stages": {"raw_growth_cagr": 0.0761952516499298, "stage1_growth": 0.05333667615495086,
                               "growth_clamped": false, "discount_rate": 0.1}},
  "data_quality": {"warnings": [{"code": "ttm_stitched", "dimensions_affected": ["valuation"]},
                                {"code": "fundamentals_stale_vs_price"}]}
}
```

The Buffett persona's narration of a comparable diagnosis, from a recorded
panel review (`research/panel-review/CCL-2026-07-29-panel.md`):

> **Buffett** — bearish, 53/100 confidence, 7/22 (pricing power excluded): moat 0/5 across the board; margin of safety −6.35%.
>
> The biggest ship in the harbor, but a big ship burns a lot of fuel: debt/equity 1.92, current ratio 0.33 — this company owes a great deal and keeps little in the till. The moat scored 0/5 (ROE above 15% in only 2 of 10 periods, average operating margins of −45.8% across the decade), and the 10-K's talk of a "powerful competitive advantage" earned no points — fine words, but the decade's numbers didn't back them. Intrinsic value of $35.9B against a $38.3B market cap is a near-miss on price, and a near-miss buys no cushion in a business this leveraged.

Every figure in that paragraph is in the engine's JSON; the eval harness below
checks exactly that.

## The whales

| Whale | Style, in one line | How it judges | Rubric |
|---|---|---|---|
| **Buffett** | Wonderful business at a fair price | Moats, owner earnings, a two-stage DCF with a growth clamp | v3, 27 points |
| **Graham** | Cheap and safe, by the numbers | Earnings stability, financial strength, net-net and the Graham Number | v1, 16 points |
| **Lynch** | Growth at a reasonable price | Classifies the company, then gates the signal on PEG | v2, 15 points |

Snapshots are whale-agnostic raw data: fetch once, and any whale scores from
the same file. A rubric change bumps `rubric_version` (every diagnosis carries
it) and regenerates golden files under review — never a silent edit. Missing or
degenerate inputs hard-fail: the whale "walks away", which the panel treats as
a first-class position rather than an error to hide.

Beside the whales sits a **portfolio layer** that renders no verdict at all: it
equal-weights a client-chosen basket and reports pairwise correlation (flag at
ρ ≥ 0.80) and sector concentration (flag above 40% of names) from pinned weekly
price history. Its narration is a fixed set of pinned sentences with slots.

## How to use it

All engine commands run from `whale_engine/`. Fetching needs `EDGAR_IDENTITY`
(your name + email — the SEC requires it); price history needs a free
`ALPHAVANTAGE_API_KEY`. Nothing else is networked.

**In Claude Code:**

| Skill | What it does |
|---|---|
| `/buffett TICKER`, `/graham TICKER`, `/lynch TICKER` | one whale's diagnosis, narrated in its voice |
| `/panel TICKER` | all three in parallel plus an agreement/disagreement synthesis — no combined verdict |
| `/portfolio T1 T2 …` | basket sanity check: equal weights, correlation and sector flags, pinned caveat |

**On the command line (numbers only):**

```bash
cd whale_engine
uv run whale fetch AAPL                       # EDGAR filings + Cboe close -> snapshots/AAPL-<date>.json
uv run whale fetch STUB --sector-only         # SIC code only, for names too young to score
uv run whale diagnose AAPL --whale buffett    # score a snapshot (offline, deterministic)
uv run whale diagnose AAPL --whale graham --snapshot snapshots/AAPL-2026-07-27.json
uv run whale prices V MA KO                   # pin weekly adjusted closes -> snapshots/prices/
uv run whale portfolio V MA KO                # equal-weight basket report (offline)
uv run whale fetch-13f                        # latest two 13F periods for the whale roster
uv run whale holdings AAPL                    # who on the roster holds it, and what they did last quarter
uv run buffett fetch|diagnose AAPL            # Buffett-pinned alias of the generic CLI
uv run pytest -q                              # the engine's tests (offline; sockets are blocked)
```

## What lives where

- `whale_engine/` — the Python engine (a `uv`-managed package)
  - `src/whale_engine/fetch.py` — EDGAR + Cboe fetch, TTM stitching, market-cap derivation
  - `src/whale_engine/validation.py` — snapshot checks: stitched windows, stale
    fundamentals, share-split renormalization, restatements, market-cap bounds
  - `src/whale_engine/scorers/` — one rubric per whale, each with `RUBRIC_VERSION`
  - `src/whale_engine/portfolio.py`, `prices.py` — the basket layer and its price pins
  - `src/whale_engine/thirteenf.py`, `holdings.py` — 13F roster and holdings scan
  - `snapshots/` — pinned filing data, one JSON per ticker per day, committed so
    every diagnosis in this repo is reproducible
  - `tests/` — unit, golden, end-to-end and narration-contract tests
- `.claude/agents/` — the personas: how each whale talks and what it may and may not say
- `.claude/skills/` — the `/buffett`, `/graham`, `/lynch`, `/panel`, `/portfolio` commands
- `research/` — the decision records behind the design: data-source and
  vendor comparisons, market-cap sourcing, the first-run audit that produced the
  validation layer, and `panel-review/` — recorded panel narrations used as eval fixtures
- `portfolios/` — real 13F holdings (e.g. Berkshire's) for context

## Evals

`whale_engine/tests/test_narration_contract.py` replays every recorded panel
narration in `research/panel-review/` against the diagnoses the engine
produces today from the same pinned snapshot, and asserts:

1. every `data_quality` warning code the diagnoses carry is mentioned in the
   narration (via a small code → phrase vocabulary; an unknown code fails);
2. every number in the narration with two or more significant digits — years
   and dates excluded — appears among the diagnoses' numeric values, up to the
   narration's own rounding and its `%` / `$T` / `$B` / `$M` presentation;
3. the pinned verbatim strings in the portfolio persona are readable from the
   prompt and present in any recorded portfolio narration.

Narrations that cannot pass today are `xfail(strict=True)` with the leaked
tokens named in the reason, and a companion test asserts each reason still
matches exactly today's leaks. Currently: one panel recorded before the
market-cap witness gate (the engine now refuses that snapshot), and one
figurative number. Golden files for all three scorers and the portfolio layer
are checked for drift in CI (`make_golden_*.py --check`).

## Provenance

The per-whale scoring rubrics (which ratios, which thresholds, how many
points) are adapted from the analyst heuristics in the open-source
[ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) project (MIT).
Everything else — the deterministic engine, hard-fail missing-data semantics,
versioned rubrics, golden-file tests, and the panel orchestration — is original
to this repo. Comments that mention "the upstream ai-hedge-fund heuristics"
compare against those.

## Ground rules

- **The engine computes; Claude narrates.** No number in any diagnosis comes
  from the AI. If data is missing, the engine hard-fails and the whale
  "walks away" — it never guesses.
- **Scoring rules are versioned.** Every diagnosis records its `rubric_version`.
  Changing Buffett's rules requires an owner-signed review — never a silent edit.
- **The panel never averages.** It reports each whale's verdict and attributes
  disagreements to their differing models.

## Built with

Built with [Claude Code](https://claude.com/claude-code) as pair-programmer:
the design was argued out in grilling sessions, the decisions are recorded in
`research/` and in the commit bodies (which is why commits carry a
`Co-Authored-By: Claude Code` trailer), and every persona is itself a Claude
Code subagent whose prompt is versioned (`PROMPT_VERSION`) like the rubrics.
Engine: Python 3.11, [edgartools](https://github.com/dgunning/edgartools),
pandas, `uv`, pytest, ruff, mypy. MIT licensed.
