# Greenblatt persona sample — V, snapshot 2026-10-13, prompt v2 / rubric v2

Produced 2026-10-13 by `/greenblatt V` from a fresh headless `claude -p` process (a same-session subagent probe still reported prompt v1, so the edited definition was sampled out of process), against the pinned snapshot `whale_engine/snapshots/V-2026-10-13.json`. Coverage role: re-sample of the asset-light case after the #112 prompt v2 pins (tests-first verdict line, asset-light slot closed, `$` format). Compare with `V-2026-10-13-greenblatt.md` (prompt v1). Recorded verbatim.

Reviewer notes: the three v1 faults are gone (no "other people's money" sentence, verdict opens with the tests, every money figure carries `$`). The as-is rule now exposes raw float reprs (`$706,196,495,430.1799`, `-$8,296,000,000.0`) — an engine-side money-rounding question, not a narration one; left for the owner.

---

greenblatt narration · prompt v2 · rubric_version 2

**Verdict.** Neutral: return on capital scored asset-light (full marks, no ratio), after-tax earnings yield 2.94% vs the 6% hurdle. That is 5 of 10 points, 73/100 confidence after a 10-point data-quality deduction.

**The business.** Capital is at or below zero with positive EBIT: the formula scores this asset-light, full marks and no ratio. "Capital -3,518,000,000 <= 0 with EBIT 26,296,000,000 > 0: asset-light (return on capital unbounded) ✓ (+5)". On tangible capital, net working capital is -$8,296,000,000.0 and net fixed assets are $4,778,000,000.0 (PropertyPlantAndEquipmentNet@2026-03-31), giving capital of -$3,518,000,000.0. There is no filings sidecar, so there is no line identifying the business.

**The price.** After-tax earnings yield 2.94% against the 6% bond hurdle. "After-tax earnings yield 2.9% < 3.0% (0.5x the 6% bond hurdle) ✗ (+0)". Trailing EBIT is $26,296,000,000.0, taxed at 21%. Enterprise value is $706,196,495,430.1799. It is built from market cap ($694,624,495,430.1799) plus short-term debt ($1,559,000,000.0) plus long-term debt ($22,417,000,000.0) minus cash and equivalents ($12,404,000,000.0). Greenblatt compares the yield with what a government bond pays and never accepts less than 6%. This engine fixes the hurdle at 6% and does not look up a live bond rate. The yield is well short of the hurdle, so this half scores nothing.

**Normal earnings.** Trailing EBIT $26,296,000,000.0 against a five-year average of $20,641,200,000.0 (ratio 1.274), covering fiscal years ending 2021-09-30 through 2025-09-30. There is no peak-earnings flag. Last year's earnings serve a basket but can mislead on one company.

**Caveats.**
- Flag: "asset_light: capital (NWC + NFA) <= 0 with positive EBIT; return on capital scored full marks without a ratio".
- **Operating income** (feeds both tests, return_on_capital and earnings_yield): some quarters were calculated from year-to-date or annual figures rather than reported directly.
- **Operating income** (also affects return_on_capital and earnings_yield): the trailing-twelve-month window ends 2026-03-31, 275 days before the 2026-12-31 reference date, so the figure may be stale.
- **Books vs price** (affects return_on_capital and earnings_yield): the price is from today, but the books are 196 days older (period ending 2026-03-31).
- **Other stitched fields:** capital expenditure, depreciation and amortization, dividends, share issuance and buybacks, net income and revenue each carry two warnings. Some quarters were calculated from year-to-date or annual figures, and each trailing-twelve-month window ends 2026-03-31, 275 days before the reference date. That is 12 warnings, none tied to a scored dimension.
- **Filings extraction failed:** Item 1 and Item 7 could not be pulled from 10-K 0001403161-25-000089, and no sidecar was written. That is 3 warnings.
- **Share-count check skipped:** EDGAR has no weighted-average share count to check the five-class cover-page share sum against, so the 1.4x mismatch guard did not run. This finding is on the snapshot but not in `data_quality.warnings`. Market cap depends on that sum.
- Confidence 73/100 after a 10-point data-quality deduction.
- Insiders: no buy cluster in trailing 12 months. The formula does not look at insiders.
- Good business, not a bargain: critics of the formula (Gray and Carlisle) find most of its return comes from the earnings-yield half, and that is the half this name fails.
- **Provenance:** snapshot `snapshots/V-2026-10-13.json`, fetched 2026-10-13. Fundamentals come from SEC EDGAR via edgartools 5.43.0 and the price from Cboe delayed quotes. SIC is 7389 and the quarterly period is 2026-03-31. Net fixed assets use the tag PropertyPlantAndEquipmentNet@2026-03-31.

The magic formula's evidence is for a basket of 20 to 30 names held a year and rebalanced; this is one name scored on one snapshot, which Greenblatt's own rule says needs an estimate of normal earnings this engine does not make. The score is a screen, not the formula's track record.
This is a mechanical rubric plus narration, not investment advice.
