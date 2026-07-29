# Panel review sample — MSFT, snapshot 2026-07-29

Produced for judgment-review ticket #74 (map #71) by the `/panel` skill: fresh fetch → buffett/graham/lynch fanned out in parallel → synthesis per the #72 contract. Coverage role: chosen as the broad-agreement case — the panel run showed a genuine three-way split instead (see synthesis).

---

## Panel — MSFT (snapshot 2026-07-29)

- **Buffett** — bearish, 59/100 confidence, 22/27: wonderful company, wrong price — margin of safety −54%.
- **Graham** — bearish, 73/100 confidence, 7/16: margin of safety −62.8%; deep-overprice override in force.
- **Lynch** — bullish, 56/100 confidence, 11/15 (stalwart): PEG 1.67 — reasonable for a stalwart of this quality.

### Buffett's read
The kind of tollbooth he likes to own: moat 4/5 (ROE above 15% in all 10 periods, averaging 33.4%), fundamentals 6/7 (debt/equity 0.10), book value 5/5, management 2/2 with $20.2B of net buybacks and $25.9B of dividends TTM. But owner earnings are $86.3B — maintenance capex of $80.8B eats most of the $125.2B in net income — and the DCF puts intrinsic value at $1.32T against a $2.90T market cap. You're paying more than double what the cash flows support: 22 of 27 points and still bearish.

### Graham's read
A fine business at an indefensible price. Earnings stability 4/4, financial strength 3/5 (debt ratio 0.40, dividends 10 of 10; only the 1.28 current ratio fails), but valuation 0/7: the Graham Number of $145.44 against a $390.52 price is a −62.8% margin of safety, at which point his deep-overprice override forces bearish on price alone. The buyer today pays for many years of future prosperity in advance — speculation on growth, not investment on value.

### Lynch's read
About as clean a two-minute drill as a stalwart gets: everyone you know uses this stuff. Growth 4/6 (revenue and EPS both compounding near 14%), fundamentals a perfect 4/4 (debt/equity 0.10 — "balance sheet like this, you don't lose sleep"), and a P/E of 23.17 against 13.9% EPS growth gives a PEG of 1.67 — under his GARP gate of 2. Not a bargain, but a reasonable price for the growth, and the bullish signal stands on its own merits.

### Synthesis
On the business, the panel is as close to unanimous as three rubrics get: the same 0.10 debt/equity earns full marks from Buffett and Lynch and passes Graham's debt test; the same decade of ROE above 15% drives Buffett's moat; the same unbroken EPS record fills Graham's stability score. Nobody disputes the quality. Buffett's own summary — "wonderful company, wrong price" — could caption the whole panel's quality columns.

The verdicts still split 180 degrees, and the split is entirely about *which yardstick prices the future*. Graham anchors to the present: EPS times book value certifies $145.44, the market asks $390.52, conversation over — and his 73 confidence, the panel's highest, reflects how far outside his zone the price sits. Buffett will pay for the future, but only what a 10%-discounted stream of owner earnings supports — and here the AI buildout works against the signal, because $80.8B of maintenance capex shrinks the very cash stream his DCF capitalizes. Lynch prices the future *as a rate*: he doesn't ask what the cash flows certify, he asks whether the multiple is fair for the growth — 1.67 times the growth rate says yes. The same $2.90T price tag is "more than double what the cash flows support" to Buffett, "many years of future prosperity in advance" to Graham, and 1.67 times the growth rate to Lynch — three yardsticks, one price, opposite conclusions.

Note the confidence inversion: the lone bullish voice is also the least confident (Lynch, 56 — his signal sits near his own bullish boundary), while the most confident whale (Graham, 73) is rendering the least surprising verdict his model can render. The disagreement here is the product working as intended — a growth-pricing model *should* read a quality compounder differently than two present-value models.

The thread to pull is Buffett's capex line: whether that $80.8B is truly maintenance or is growth investment in disguise decides whether his owner-earnings figure — and with it the panel's widest bearish margin — is fair to the business.

### Caveats (panel-level)
- All three diagnoses rest on the same snapshot: fetched 2026-07-29 from SEC EDGAR (edgartools 5.43.0); price from Cboe delayed close; books end 2026-03-31 — the price is 120 days fresher than the fundamentals, touching valuation everywhere.
- Shared stitched-TTM family: revenue, net income, operating income, gross profit, capex, D&A, dividends, and buybacks are stitched from YTD/annual filings rather than directly reported quarters — this cost Buffett a 15-point confidence dock and touches scored dimensions in all three rubrics. D&A has only 7 of the recommended 8 quarters.
- No scoring flags in any whale — no share renormalizations, no restatement exclusions.
- Insider activity (context only, all whales): no buy cluster in trailing 12 months; the one open-market purchase is Director John W Stanton, 5,000 shares (~$1.99M) on 2026-02-18.

These are mechanical rubrics plus narration, not investment advice. Full single-whale diagnoses: `/buffett MSFT`, `/graham MSFT`, `/lynch MSFT`.
