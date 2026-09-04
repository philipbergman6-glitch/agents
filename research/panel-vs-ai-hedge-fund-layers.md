# /panel vs. ai-hedge-fund's aggregation layers

**Date:** 2026-07-28. **Question:** what does our panel layer give us against the layers `virattt/ai-hedge-fund` puts on top of its analyst agents? **Sources:** `src/agents/portfolio_manager.py` (262 lines) and `src/agents/risk_manager.py` (317 lines) fetched from the repo's `main` today; our `.claude/skills/panel/SKILL.md`. Our scoring rubrics are adapted from that project (see README "Provenance"), so this is a comparison against our own upstream.

## Their stack (observed, not assumed)

Three layers:

1. **Analyst layer** (~20 agents: investor personas + technicals/sentiment/fundamentals/valuation). Each computes sub-scores in Python but the final `{signal, confidence, reasoning}` comes from an LLM call — `warren_buffett.py` says so directly: *"Analyzes stocks using Buffett's principles and LLM reasoning."*
2. **Risk manager** (deterministic Python, needs price history from the paid FinancialDatasets API). Position limit per ticker = portfolio value × volatility tier (annualized vol <15% → up to 25% allocation … >50% → max 10%; `calculate_volatility_adjusted_limit`) × correlation multiplier (avg correlation with active positions ≥0.8 → 0.70x … <0.2 → 1.10x; `calculate_correlation_multiplier`). Output: `remaining_position_limit` in dollars.
3. **Portfolio manager**. Deterministically computes allowed actions per ticker from cash/margin (`compute_allowed_actions`), compresses every analyst signal to `{sig, conf}` (`_compact_signals`), then hands the whole thing to an LLM: *"You are a portfolio manager… Pick one allowed action per ticker and a quantity ≤ the max. Keep reasoning very concise (max 100 chars)."* LLM failure → default `hold`.

## What their layers give that /panel doesn't

- **A bottom line**: buy/sell/short/cover/hold + share quantity per ticker.
- **Position sizing** from volatility and cross-position correlation.
- **Portfolio context**: cash, margin, existing positions, multi-ticker batches.

## What /panel gives that theirs doesn't

1. **Deterministic signals.** Their per-analyst signal is itself an LLM output — same inputs can produce different verdicts run to run. Ours is byte-identical from the same snapshot, with `rubric_version` and snapshot provenance on every diagnosis. Their prompts are unversioned.
2. **Honest aggregation.** The hard question — how to weigh 20 conflicting signals — they delegate to an unversioned LLM prompt with no stated aggregation rule, and cap its accountability at 100 characters of reasoning. Panel refuses to aggregate at all: divergence is model-attributed, disagreement is the product. We don't have a hidden opinion pretending to be arithmetic.
3. **No signal dilution.** `_compact_signals` strips every signal to `{sig, conf}` before the decision — the PM LLM never sees *why* Buffett was bullish. Panel's inputs are the whales' full narrations.
4. **Hard-fail discipline.** Their risk manager, on missing price data, silently assumes 5% daily volatility and continues (`"daily_volatility": 0.05  # Default fallback`). Our whales walk away, and the panel reports the walk-away as a first-class position.
5. **Free, auditable data.** EDGAR-only vs. a paid API key requirement.

## Read-across to our roadmap

- Their **risk manager is the codifiable part** and maps almost exactly onto our deferred portfolio layer (1/N + correlation/sector sanity check from pinned price history). Their vol-tier limits are deterministic and borrowable if that layer ever revives — though it deliberately chose 1/N over cleverness (DeMiguel 2009).
- Their **portfolio manager is the cautionary tale**: it's what the "mechanical tally" we deferred looks like when built without a stated rule — an LLM vibe-weighting compressed signals. If clients ever demand a combined verdict, the bar set here is: versioned, deterministic, stated aggregation rule, or don't ship it.

## Client-facing one-liner

They built an autonomous trader whose judgment is an unversioned prompt; we built an audit-grade research panel whose judgment is versioned code — and where the AI is only ever allowed to explain, never to decide.
