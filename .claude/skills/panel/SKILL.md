---
name: panel
description: Panel diagnosis — /panel TICKER. Fans out the buffett, graham, and lynch subagents in parallel and synthesizes a narration-only agreement/disagreement view. Never renders a combined verdict.
---

Run the three-whale panel on $ARGUMENTS. You orchestrate and synthesize; the whales diagnose; the engine computes. You never produce a number that does not appear in a whale's output — no averages, no tallies, no re-derived figures.

# Procedure

1. Resolve the ticker from the request (e.g. "Apple" → AAPL).
2. **Fetch once, before fan-out.** From the `whale_engine/` directory, check for a snapshot fetched today: `ls snapshots/<TICKER>-$(date +%F).json`. If missing, run `uv run whale fetch <TICKER>` once (needs network and `EDGAR_IDENTITY`; if unset, ask the user for their name and email — never invent one). The subagents will find this snapshot themselves; fetching here exists so three agents never race or triple-fetch.
   - If the fetch fails and an older snapshot exists: report the fetch error, tell the user the newest snapshot's date, and proceed only if they say so. A stale panel is all-stale-or-none — never mix snapshot vintages across whales.
   - If the user names a specific snapshot file, skip fetching and pass that file to all three subagents (the audit/reproducibility path).
3. **Fan out in parallel** — a single message with three Agent tool calls, one each to the `buffett`, `graham`, and `lynch` subagents: "Diagnose <TICKER>." (plus the snapshot file if the user named one). Never diagnose a whale yourself, and never re-derive a whale's view from raw engine JSON — the personas' narrations are the panel's inputs.
4. **Synthesize** per the output format below. If a whale reports a hard-fail (`MissingDataError`), that is a first-class position — "walks away" — not an error to hide or retry; the panel proceeds over the whales that scored and says so.

# Output format (~600–800 words total)

1. **Panel** — one verdict line per whale: signal, confidence, score, and its key driver, e.g.
   - **Buffett** — bullish, 85/100 confidence, 78/100: zero-growth DCF still shows margin of safety.
   - **Lynch** — neutral, 83/100 confidence, 9/15 (stalwart): GARP gate — PEG 2.4.
   A whale that hard-failed gets its line too: **Lynch** — walks away: filings lack a resolved debt component.
2. **Per-whale gists** — 2–3 sentences each (a walks-away gist may run to 4 — hard-fails take more explaining), faithful to that whale's own narration and voice; no editorializing. Round dollar figures to human scale ($1,594,055,850 → $1.59B) — rounding is presentation, not computation; ratios, scores, and percentages stay exactly as the whale reported them.
3. **Synthesis** — agreements first, then divergences:
   - Attribute every divergence to the *models*: DCF vs PEG vs asset tests, differing confidence, or data-quality differences. Never say the panel "leans," "favors," or "on balance" anything.
   - Narrate unanimity factually ("three orthogonal models independently reach bullish") — that observation is the closest the panel ever comes to a bottom line.
   - If the panel is reduced by a hard-fail, label it as such and name why that whale walked.
   - When multiple whales hit the same data gap, narrate how each treated it (one fell back to a looser test, one scored it zero, one walked) — the spread of treatments is itself information.
   - When a whale's confidence and verdict point in opposite directions — the lone dissenter is the least confident, or the most confident whale is rendering its least surprising verdict — say so, and say what the confidence attaches to.
4. **Shared caveats** — once, at panel level: snapshot date and provenance, data-quality warnings the whales surfaced, fundamentals-vs-price staleness. Whale-specific caveats stay attributed to that whale. End with one line noting these are mechanical rubrics plus narration, not investment advice.

# Prohibitions

- No combined verdict, vote, or tally — no "2 of 3 bullish," no counting language, no averaged or aggregated scores.
- No numbers absent from the whales' outputs; no cross-whale arithmetic of any kind.
- Every figure in the panel — including ratios and multiples in the synthesis — must appear in a whale's narration; human-scale rounding is the only permitted transformation. If you want a comparison a whale didn't compute, quote the whale's own words instead ("more than double what the cash flows support"). Synthesis compression will tempt you to derive ratios; don't.
- Never soften, override, or reconcile a whale's verdict — disagreement is the product, not a problem.
- Full single-whale diagnoses are not concatenated here; point the user at /buffett, /graham, /lynch for depth.
