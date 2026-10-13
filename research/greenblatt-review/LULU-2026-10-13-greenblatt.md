# Greenblatt persona sample — LULU, snapshot 2026-10-13

Produced 2026-10-13 by `/greenblatt LULU` (`.claude/agents/greenblatt.md` prompt v1, rubric_version 1) for the judgment review ticket, from a fresh headless `claude -p` process against the pinned snapshot `whale_engine/snapshots/LULU-2026-10-13.json` (fetched that day, so the subagent ran no fetch). A fresh process loads the subagent definition at start, so no definition-staleness probe was needed. Coverage role: the bullish case (10/10, both tests full marks, no critique line). Recorded verbatim, including the relay wrapper lines.

---

greenblatt narration · prompt v1 · rubric_version 1

**Verdict**
Bullish. Confidence 90/100 after a 10-point data-quality deduction. 10 of 10 points: return on capital 70.66%, after-tax earnings yield 18.16% vs the 6% hurdle.

**The business**
Return on capital 70.66%: the good-business test. "Return on capital 70.7% >= 25% ✓ (+5)". That return is on tangible capital, and goodwill is never counted. Net working capital is $754,199,000 with cash removed. Net fixed assets are $2,046,363,000 (PropertyPlantAndEquipmentNet@2026-08-02). Capital comes to $2,800,562,000. The business ties up little and earns a lot on it. No filings sidecar was written, so there is no identification line from the 10-K.

**The price**
After-tax earnings yield 18.16% against the 6% bond hurdle. "After-tax earnings yield 18.2% >= 6.0% (1x the 6% bond hurdle) ✓ (+5)". Trailing EBIT is $1,978,775,000, taxed at a 21% rate. Enterprise value is $8,605,797,098.24. It is built from market cap $9,995,534,098.24, plus short-term debt of $0.0 and long-term debt of $0.0, minus cash of $1,389,737,000. Greenblatt compares this yield with a risk-free government bond, with 6% as the floor. This engine fixes the hurdle at 6% and does not look up a live bond rate.

**Normal earnings**
Trailing EBIT $1,978,775,000 against a five-year average of $1,902,150,200 (ratio 1.0403). The average covers the annual periods ending 2026-02-01, 2025-02-02, 2024-01-28, 2023-01-29 and 2022-01-30. There is no peak-earnings flag. Last year's earnings work fine across a basket of stocks but can mislead on one company. Here trailing EBIT sits close to its own average, which is about as normal as a single year gets.

**Caveats**
- **Flag:** "long_term_debt: missing, treated as 0 in enterprise value (short_term_debt resolved)". If LULU does carry long-term debt, its enterprise value is understated and the yield is overstated.
- **Stitched data:** some trailing-twelve-month figures were calculated from year-to-date or annual filings, not reported directly by quarter. That covers operating income, which affects both scores (return on capital and earnings yield). It also covers revenue, net income, gross profit, capex, depreciation and share issuance or buybacks, none of which affects a score.
- **Sidecar failures:** the engine could not slice Item 1 or Item 7 from 10-K 0001397187-26-000020, so no sidecar was written. Nothing in the scoring depends on it.
- **Staleness:** there is no fundamentals-staleness warning. The books run to the 2026-08-02 quarter and the price is the 2026-10-12 close.
- Confidence 90/100 after a 10-point data-quality deduction.
- **Insiders:** no buy cluster in trailing 12 months. The formula ignores insiders anyway.
- **Critique line:** none, because both tests scored 5 of 5.
- **Provenance:** snapshot snapshots/LULU-2026-10-13.json, fetched 2026-10-13. Fundamentals come from SEC EDGAR via edgartools 5.43.0 and the price from CBOE delayed quotes. SIC 2300, quarter ending 2026-08-02, net_fixed_assets_tag PropertyPlantAndEquipmentNet@2026-08-02.

The magic formula's evidence is for a basket of 20 to 30 names held a year and rebalanced; this is one name scored on one snapshot, which Greenblatt's own rule says needs an estimate of normal earnings this engine does not make. The score is a screen, not the formula's track record.
This is a mechanical rubric plus narration, not investment advice.

---
Files:
- Snapshot (fetched today, so no refetch was needed): /Users/philipbergman/Documents/Coding_Projects/agents/whale_engine/snapshots/LULU-2026-10-13.json
- `EDGAR_IDENTITY` is not set in this shell. You'll need it for any future refetch.
