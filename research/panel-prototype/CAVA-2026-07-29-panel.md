# Panel prototype output — CAVA, snapshot 2026-07-29

Produced by the draft `/panel` skill (`.claude/skills/panel/SKILL.md`) for prototype ticket #73 (map #71).
This is the **hard-fail sample**: chosen because one whale walks away, exercising the reduced-panel branch of the #72 contract.
Procedure followed: no snapshot for today → `whale fetch CAVA` once → buffett/graham/lynch subagents fanned out in parallel → synthesis per the locked contract.

---

## Panel — CAVA (snapshot 2026-07-29) — reduced: Lynch walks away

- **Buffett** — bearish, 56/100 confidence, 12/27: negative owner earnings; DCF margin of safety −102.2%.
- **Graham** — bearish, 86/100 confidence, 7/16: margin of safety −86.0% vs the Graham Number; deep-overprice override in force.
- **Lynch** — walks away: neither short- nor long-term debt resolved in the latest quarter; refuses to score D/E.

### Buffett's read
A young chain with a short record: fundamentals 3/7, moat 0/5 (operating margins averaged −2.3% across the window), book value the lone bright spot at 5/5. Owner earnings are negative — −$14.5M after $145.7M of maintenance capex against $61.6M of net income — so the DCF yields negative intrinsic value against a $7.57B market cap. His line: you cannot pay $7.6 billion for a machine that currently consumes cash and call it a bargain.

### Graham's read
The enterprise itself tests respectably — EPS positive in 8 of 9 periods, current ratio 2.65, debt ratio 0.43 — but valuation is 0/7 and the −86.0% margin of safety versus the $9.10 Graham Number triggers his deep-overprice override: price alone rules the name out. A "sound business, indefensible price" reading — the score condemns the $65.04 quotation, not the restaurants. His 86 confidence attaches to how far outside his zone the price sits.

### Lynch's read
No verdict. The engine hard-failed: the latest quarter (2026-04-19) resolves neither short- nor long-term debt, and debt-to-equity is a scored dimension. Unresolved tags are not the same as zero debt — restaurant operators often carry leases and credit facilities under nonstandard concepts — so rather than guess, he walks. If you can't run the two-minute drill on the balance sheet, you don't own the stock.

### Synthesis
**The panel is reduced.** Lynch's walk is a data-integrity position, not an error: the same unresolved-debt gap the other two whales flagged and scored *around*, his rubric treats as disqualifying. Note the three treatments of one gap — Buffett fell back to a looser total-liabilities test (and says so), Graham scored debt-dependent checks 0 as a data gap, Lynch refused to score at all. That spread is itself information about how much of CAVA's balance-sheet picture rests on convention.

Among the whales that scored, two orthogonal models independently reach bearish — but for model-distinct reasons. Buffett's bearish is about the *business's cash economics*: growth capex swallows earnings, so his ten-year DCF has nothing to capitalize and defaults to negative intrinsic value. Graham's bearish is purely about *price*: he explicitly credits the enterprise (earnings stability 3/4, financial strength 4/5) and condemns only the quotation. The confidence gap runs the same seam — Graham's 86 reflects a price unambiguously outside his tests; Buffett's 56 carries a 15-point dock because his fundamentals, management, and valuation dimensions all rest on flagged or stitched data.

The thread to pull: Buffett notes TTM net income fell from $142.0M to $61.6M while book value kept compounding — Graham's "respectable" EPS record is built on the period before that slide.

### Caveats (panel-level)
- Both scoring diagnoses rest on the same snapshot: fetched 2026-07-29 from SEC EDGAR (edgartools 5.43.0); price from Cboe delayed close; latest fundamentals end 2026-04-19 — the price is 101 days fresher than the books.
- Shared data-quality family: TTM revenue, net income, operating income, gross profit, capex, D&A, and issuance/buybacks are stitched from YTD/annual filings, not directly reported quarters; stale gross-profit windows (up to 560 days) were discarded.
- IPO artifacts: share counts jump ~80× into 2023, so pre-IPO periods are excluded from per-share history; the 2023-04-16 balance sheet fails the assets = liabilities + equity identity (pre-IPO mezzanine equity).
- The unresolved-debt gap that Lynch walked on also touches the scoring whales: Buffett's leverage points came from a fallback liabilities test, and Graham's debt-dependent checks scored 0.
- Insider activity (context only): no buy cluster in trailing 12 months.

These are mechanical rubrics plus narration, not investment advice. Full single-whale diagnoses: `/buffett CAVA`, `/graham CAVA`, `/lynch CAVA`.
