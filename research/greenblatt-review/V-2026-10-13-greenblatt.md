# Greenblatt persona sample — V, snapshot 2026-10-13

Produced 2026-10-13 by the `greenblatt` subagent (`.claude/agents/greenblatt.md` prompt v1, rubric_version 1) for the judgment review ticket (#112), from the pinned snapshot `whale_engine/snapshots/V-2026-10-13.json` (fetched that day; no fetch run). Coverage role: the asset-light case (capital ≤ 0 with positive EBIT → return on capital 5 without a ratio; earnings yield 0; neutral 5/10). Recorded verbatim; `&lt;`/`&gt;` are relay-escaped `<`/`>` from the engine's details line.

Review notes (reviewer, not the subagent): dollar signs dropped throughout, unlike the LULU/META samples; "Visa runs on other people's money" is a qualitative claim the prompt forbids; the stitched-warning bullet is fuller than LULU/META's because this snapshot also carries `ttm_stale_window` (275 days) and `fundamentals_stale_vs_price` (196 days).

---

greenblatt narration · prompt v1 · rubric_version 1

**Verdict.** Neutral, 73/100 confidence after a 10-point data-quality deduction. Score is 5 of 10 points. Return on capital is scored asset-light, with no ratio. After-tax earnings yield is 2.94% against the 6% hurdle.

**The business.** Capital is at or below zero with positive EBIT: the formula scores this asset-light, full marks and no ratio. "Capital -3,518,000,000 &lt;= 0 with EBIT 26,296,000,000 &gt; 0: asset-light (return on capital unbounded) ✓ (+5)". Capital here means tangible capital: no cash, no goodwill. Net working capital is -8,296,000,000. Net fixed assets are 4,778,000,000 (PropertyPlantAndEquipmentNet@2026-03-31). Together they make capital of -3,518,000,000. Visa runs on other people's money and earns 26.3 billion on it, so the good-business test passes easily. No filings sidecar was written for this snapshot, so there is no line from the filing describing the business.

**The price.** After-tax earnings yield 2.94% against the 6% bond hurdle. "After-tax earnings yield 2.9% &lt; 3.0% (0.5x the 6% bond hurdle) ✗ (+0)". The inputs are EBIT of 26,296,000,000 and a tax rate of 21%. Enterprise value is 706,196,495,430.18. It is built from market cap (694,624,495,430.18) plus short-term debt (1,559,000,000) plus long-term debt (22,417,000,000) minus cash and equivalents (12,404,000,000). Greenblatt compares this yield with a government bond and treats 6% as the floor. This engine fixes the hurdle at 6% and does not look up a live bond rate. A bond would pay you more per dollar than this business earns per dollar of price. The bargain-price test fails.

**Normal earnings.** Trailing EBIT 26,296,000,000 against a five-year average of 20,641,200,000 (ratio 1.274), covering the fiscal years ended 2021-09-30 through 2025-09-30. The peak-earnings flag is not set. Greenblatt's own caveat is that last year's earnings serve a basket but can mislead on one company.

**Caveats.**
- Flag: "asset_light: capital (NWC + NFA) &lt;= 0 with positive EBIT; return on capital scored full marks without a ratio".
- Each of these fields carries two warnings: capital expenditure, depreciation and amortization, dividends, share issuance/repurchase, net income, revenue and operating income.
  - The first warning says some quarters from 2023-12-31 through 2025-12-31 were stitched together from year-to-date or annual filings rather than reported directly.
  - The second says the TTM window ending 2026-03-31 lags the reference date by 275 days and may be stale.
  - Only the operating income warnings affect scored dimensions: **return_on_capital** and **earnings_yield**.
- Fundamentals are stale against the price. The price is from today, but the books (period ending 2026-03-31) are 196 days older. This affects **return_on_capital** and **earnings_yield**.
- Three warnings come from the filings sidecar step. The engine failed to extract Item 1 and Item 7 from 10-K 0001403161-25-000089, extracted no items at all, and wrote no sidecar.
- One more finding sits in the snapshot's validation list: EDGAR has no weighted-average share count to cross-check the sum of the five share classes, so the 1.4x mismatch guard did not run.
- Confidence 73/100 after a 10-point data-quality deduction.
- Insiders: no buy cluster in trailing 12 months. The formula ignores insider activity anyway.
- Good business, not a bargain: critics of the formula (Gray and Carlisle) find most of its return comes from the earnings-yield half, and that is the half this name fails.
- Provenance:
  - snapshot dated 2026-10-13
  - fundamentals from SEC EDGAR via edgartools 5.43.0
  - price from CBOE delayed quotes
  - SIC 7389
  - quarterly period 2026-03-31
  - net fixed assets tag PropertyPlantAndEquipmentNet@2026-03-31

The magic formula's evidence is for a basket of 20 to 30 names held a year and rebalanced; this is one name scored on one snapshot, which Greenblatt's own rule says needs an estimate of normal earnings this engine does not make. The score is a screen, not the formula's track record.
This is a mechanical rubric plus narration, not investment advice.
