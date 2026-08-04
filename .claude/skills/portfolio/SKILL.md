---
name: portfolio
description: Basket sanity check — /portfolio TICKER…. Delegates to the portfolio subagent, which runs the deterministic engine (equal weights, pairwise correlation, sector concentration) and narrates the result. Never renders a verdict on the basket.
---

Delegate to the `portfolio` subagent via the Agent tool. Pass the whole ticker list and any user preferences (e.g. "offline", "use what's already pinned", a specific snapshots directory) through in the prompt:

> Report on the basket $ARGUMENTS.

Relay the subagent's report to the user unchanged. Do not add your own numbers, do not summarize the correlations, do not offer a view on the basket or on any company in it, and never shorten or paraphrase the closing caveat.

If the user hands you a basket sourced from whale verdicts (`/buffett`, `/graham`, `/lynch`, `/panel`), pass the tickers through as given — the client chooses the basket; the engine never admits or rejects a name, and the whales endorse neither this method nor the resulting mix.
