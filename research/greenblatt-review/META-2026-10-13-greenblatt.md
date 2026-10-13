# Greenblatt persona sample — META, snapshot 2026-10-13

Produced 2026-10-13 by `/greenblatt META` (`.claude/agents/greenblatt.md` prompt v1, rubric_version 1) for the judgment review ticket, from a fresh headless `claude -p` process against the pinned snapshot `whale_engine/snapshots/META-2026-10-13.json` (fetched that day, so the subagent ran no fetch). A fresh process loads the subagent definition at start, so no definition-staleness probe was needed. Coverage role: the neutral case (6/10: return on capital 5, earnings yield 1; peak-earnings flag; the good-business-not-a-bargain critique line). Recorded verbatim, including the relay wrapper lines.

---

Greenblatt subagent diagnosis of META, relayed unchanged:

greenblatt narration · prompt v1 · rubric_version 1

**Verdict:** Neutral, 57/100 confidence after a 10-point data-quality deduction. 6 of 10 points: return on capital 31.12%, after-tax earnings yield 3.51% against the 6% hurdle. The business passes the formula's test, but the price does not.

**The business**
Return on capital 31.12%: the good-business test. "Return on capital 31.1% >= 25% ✓ (+5)". That return is earned on tangible capital: net working capital of $53,634,000,000 plus net fixed assets of $225,724,000,000 (tag `PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization@2026-06-30`), which gives capital of $279,358,000,000. Cash is removed and goodwill is not counted. This test scores full marks. No filings sidecar was written, so there is no Item 1 description line.

**The price**
After-tax earnings yield 3.51% against the 6% bond hurdle. "After-tax earnings yield 3.5% >= 3.0% (0.5x the 6% bond hurdle) ✓ (+1)". EBIT is $86,927,000,000, taxed at a 21% rate. Enterprise value is $1,957,549,280,000. It is built from market cap ($1,889,347,280,000), plus short-term debt ($0, see flags), plus long-term debt ($83,664,000,000), minus cash ($15,462,000,000). Greenblatt compares this yield with what a risk-free government bond pays, with 6% as the lowest acceptable bar. This engine fixes the hurdle at 6% and does not look up a live bond rate. A 3.51% yield is not a bargain.

**Normal earnings**
Trailing EBIT $86,927,000,000 against a five-year average of $55,020,800,000 (ratio 1.5799), covering fiscal years ending 2021-12-31 through 2025-12-31. Peak-earnings flag: trailing EBIT runs more than 1.5x its five-year average; the formula wants a normal year, and this may not be one. Last year's earnings work for a basket but can mislead on one company.

**Caveats**
- **Flag:** "short_term_debt: missing, treated as 0 in net working capital and enterprise value (long_term_debt resolved)". A related validation note says EDGAR cannot tell an untagged fact from a true zero.
- **Stitched figures:** some trailing-twelve-month figures were pieced together from year-to-date or annual filings rather than reported quarter by quarter. This applies to:
  - operating income, which affects **return_on_capital** and **earnings_yield**;
  - capital expenditure, depreciation and amortization, dividends, equity issuance or purchase, net income and revenue, which affect no scored dimension.
- **Stale leg dropped:** an outdated component (ProceedsFromIssuanceOfCommonStock, whose last window ends 2015-12-31) was left out of equity issuance or purchase. This happened for each of the nine quarters from 2024-03-31 to 2026-06-30. No scored dimension is affected.
- **Stale books:** the price is from today, but the books end 2026-06-30, 105 days older. This affects **return_on_capital** and **earnings_yield**.
- **Filings sidecar failed:** the engine could not extract Item 1 or Item 7 from 10-K 0001628280-26-003942, so no sidecar was written. Nothing in the formula depends on it.
- Confidence 57/100 after a 10-point data-quality deduction.
- **Insiders:** no buy cluster in trailing 12 months. The formula does not look at insiders.
- Good business, not a bargain: critics of the formula (Gray and Carlisle) find most of its return comes from the earnings-yield half, and that is the half this name fails.
- **Provenance:** snapshot `snapshots/META-2026-10-13.json`, fetched 2026-10-13. Fundamentals from SEC EDGAR via edgartools 5.43.0; price from Cboe delayed close, with market cap derived from weighted-average basic shares as of 2026-06-30. SIC 7370, quarter ending 2026-06-30, net fixed assets tag as above.

The magic formula's evidence is for a basket of 20 to 30 names held a year and rebalanced; this is one name scored on one snapshot, which Greenblatt's own rule says needs an estimate of normal earnings this engine does not make. The score is a screen, not the formula's track record.
This is a mechanical rubric plus narration, not investment advice.

---
Today's snapshot was already on disk, so nothing was fetched. Snapshot: `whale_engine/snapshots/META-2026-10-13.json`
