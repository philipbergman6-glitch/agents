# Greenblatt magic formula — definitions and absolute anchors

Researched 2026-10-12 for ticket #106 (map #105). Owner quote-check: not done, fallback applied (see that section). This is the Greenblatt rubric's
"reference pin": what Greenblatt himself publishes, as short page-cited quotes, plus
what secondary sources and open-source agents add.

**Source status — read first.**

- Book quotes come from an **unofficial PDF** of *The Little Book That Beats the
  Market* (Wiley, **2006 edition**, © 2006). Page numbers are the printed page
  numbers in that PDF's running headers. Every book quote is tagged
  **UNVERIFIED — owner to check against own copy**. The 2010 "Still Beats the
  Market" edition is a revision; its pagination and appendix wording may differ
  (not checked — no copy of that edition was available).
- Quotes are a sentence or less, for verification only. No bulk book text is in
  this repo.
- Each section separates **Quoted** (observed text), **Inference** (my reading),
  and **Unverified** (claims I could not tie to a primary source).

## 1. Return on capital (ROC)

**Quoted** (2006 ed.; all UNVERIFIED — owner to check against own copy):

- p.138 — formula heading: *"EBIT/(Net Working Capital + Net Fixed Assets)"*.
- p.139 — denominator is *"tangible capital employed (Net Working Capital + Net
  Fixed Assets)"*.
- p.139 — excess cash: *"excess cash not needed to conduct the business was
  excluded from this calculation"*.
- p.140 — short-term debt: *"short-term interest-bearing debt was excluded from
  current liabilities for this calculation"*.
- p.140 (boxed NOTE) — goodwill: *"Intangible assets, specifically goodwill, were
  excluded from the tangible capital employed calculations."*
- p.141 — fixed assets: *"depreciated net cost of these fixed assets"* is added to
  net working capital.
- p.139 (footnote) — EBIT as owner-earnings proxy: it was *"assumed that EBITDA −
  Maintenance Cap/Expenditures = EBIT"* (D&A ≈ maintenance capex).

**Inference.**

- NWC = (current assets − excess cash) − (current liabilities − short-term
  interest-bearing debt). Greenblatt never defines "excess cash" numerically; any
  split between operating and excess cash is a rubric choice, not his.
- "Intangible assets, specifically goodwill" is ambiguous on whether *all*
  intangibles or only goodwill are excluded. The fixed-asset side is "net fixed
  assets" (depreciated PP&E), which already omits intangibles unless they are
  bundled in, so the practical question is only whether goodwill/intangibles sit
  inside working capital — they don't under GAAP. **Net effect: using
  NWC + net PP&E excludes goodwill automatically**; a separate goodwill field is
  only needed if the rubric wants to report the size of the exclusion.
- p.138 footnote also says *"Adjustments were also made for certain non-interest
  bearing liabilities"* — unspecified; not reproducible.

## 2. Earnings yield (EY)

**Quoted** (2006 ed.; UNVERIFIED — owner to check against own copy):

- p.141 — formula heading: *"EBIT/Enterprise Value"*.
- p.141 — EV defined as *"market value of equity* + net interest-bearing debt"*,
  footnote *"Including preferred equity."*
- p.142 (footnote) — after-tax comparison to the bond: the *"fully taxed EBIT to
  enterprise value"* *"would be the earnings yield ratio used to measure
  investment alternatives versus the risk-free 10-year government bond yield"*.
  The worked example uses a **40 percent** corporate tax rate (p.142 text and
  footnote).

**Inference.**

- EV = market cap + preferred (at market) + interest-bearing debt − cash. The book
  says "net" interest-bearing debt without saying net of *which* cash (all cash vs
  excess cash only). Rubric choice.
- **Pre-tax EBIT/EV is the ranking metric; the bond hurdle uses after-tax
  (EBIT × (1 − t))/EV.** The charter's "after-tax EBIT/EV vs 6%" matches the
  p.142 footnote. **Page note:** the charter and the prior pass cite p.143; in this
  PDF the footnote sits on p.142 (the running text continues onto p.143). Owner to
  confirm which page in their copy.
- The only tax rate Greenblatt uses is 40% (illustrative, 2006 US). He gives no
  instruction to use the company's own effective rate.

## 3. Timing — TTM flows, latest balance sheet

**Quoted** (p.138 footnote, 2006 ed.; UNVERIFIED — owner to check against own copy):
*"earnings-related numbers were based on the latest 12-month period, balance sheet
items were based on the most recent balance sheet, and market prices were based on
the most recent closing price."*

**Inference.** This maps 1:1 onto the snapshot's existing shape (TTM flow fields +
latest balance-sheet fields + a price-derived `market_cap`).

## 4. Universe exclusions and minimum size

**Quoted** (2006 ed.; UNVERIFIED — owner to check against own copy):

- p.138 (footnote, study): *"Utilities, financial stocks and companies where we
  could not be certain that the information in the database was timely or complete
  were eliminated."*
- p.53 (footnote): *"certain financial stocks and utilities are excluded from our
  stock universe"*.
- p.136 (screening instructions): *"Eliminate all utilities and financial stocks
  (i.e., mutual funds, banks and insurance companies)"*; *"Eliminate all foreign
  companies from the list."* (ADR suffix given as the usual tell).
- p.134 (Option 1, magicformulainvesting.com): market caps *"above $50 million or
  $100 million should be of sufficient size"* for most individuals.
- p.136: a very low P/E, *"say 5 or less"*, *"may indicate that the previous year
  or the data being used are unusual in some way"* — optional elimination.

**Inference / corrections to the prior pass.** The $50M/$100M line is on **p.134**
in this PDF, not p.135. The financial/utility exclusion is a *data-fit* exclusion
(EBIT/EV and NWC are meaningless for banks/insurers), not a value judgment —
consistent with the Graham/Lynch walk-away-by-SIC precedent. "Financial" per p.136
explicitly includes mutual funds, banks and insurers; REITs, BDCs and brokers are
not named.

## 5. The single-company absolute rule

This is the anchor the charter pins.

**Quoted** (2006 ed.; UNVERIFIED — owner to check against own copy):

- p.102 — ideally, instead of last year's earnings, *"we should be plugging in
  estimates for earnings in a normal year."*
- p.102 (footnote) — *"A normal year is one in which nothing extraordinary or
  unusual is happening within the company, its industry, or the overall economy."*
- p.103 — *"We could then compare the earnings yield based on normal earnings to a
  risk-free 6 percent government bond and to our other investment opportunities."*
- p.103 — *"this is precisely the way my partners and I use the principles behind
  the magic formula to make our own investment decisions."*
- p.103 — the chapter's main point: *"You have no business investing in individual
  stocks on your own!"* (for readers who cannot estimate normal earnings).
- p.104 — last year's earnings work for a portfolio, but *"for individual
  companies, this may not be the case."*

**Inference.**

- The absolute rule has **two** comparisons: EY vs the 6% bond, and EY vs "other
  investment opportunities". A single-ticker scorer can implement only the first.
- The rule assumes **normal** earnings. A TTM-EBIT scorer is exactly the mechanism
  Greenblatt says is unreliable for one company (p.104). This is the strongest
  argument for a narrated caveat and/or a cyclicality guard in rubric v1 — it is
  Greenblatt's own critique, not an outside one.
- p.103 also requires a judgment on growth and (footnote) on management — no
  snapshot field covers either.

## 6. The 6% floor

**Quoted** (p.15, 2006 ed.; UNVERIFIED — owner to check against own copy):

- *"whenever the long-term government bond is paying less than 6 percent, we will
  still assume the rate is 6 percent."*
- *"if long-term U.S. government bond rates rose to 7 percent or higher, we would
  use 7 percent or that higher number."*

**Inference.** The hurdle is max(6%, 10-year Treasury yield). The charter's fixed 6%
is faithful whenever the 10-year is ≤6% (true throughout 2008–2026 to my knowledge,
not verified here); it **under-states** the hurdle if rates ever exceed 6%. That gap
is a known, documentable simplification given "no live risk-free rate" is out of
scope.

## 7. ROC: no absolute bar exists in the book

**Quoted** (2006 ed.; UNVERIFIED — owner to check against own copy):

- p.136 — screener fallback: *"Set the minimum ROA at 25%."* — explicitly a stand-in
  (*"This will take the place of return on capital from the magic formula
  study."*), for third-party screeners that lack ROC.
- p.43–44 — illustrative only: a gum store at a *"50 percent return on capital"*
  vs *"2.5 percent"* for Just Broccoli.

**Inference.** Searching the whole text for numeric ROC thresholds finds none
besides the 25% ROA screener proxy and the illustrative 50%/2.5%. The magic formula
ranks ROC; it never says "ROC above X is good". Confirms the charter: **any ROC bar
is owner judgment**, to be signed in the rubric lock. The 25% ROA figure is the
only Greenblatt-published number in the neighborhood, but it is ROA (net income /
total assets), not ROC, and was a screener approximation.

## 8. Method context a single-ticker scorer drops

**Quoted** (2006 ed.; UNVERIFIED — owner to check against own copy):

- p.131 — plan to hold *"at least 20 to 30 stocks at one time"*.
- p.131 (footnote) — *"if you are already good at analyzing businesses ... these
  diversification rules do not apply to you."*
- p.132 / p.135 — hold each stock one year; sell losers a few days before and
  winners a few days after the one-year mark (taxable accounts).
- p.135 — commit *"for a minimum of three to five years, regardless of results."*

**Inference.** The formula's evidence is for a ~30-stock, annually rebalanced
basket. A single-name diagnosis is the p.103 "partners" use, which Greenblatt says
needs normal-earnings estimates the engine does not make. The persona must not
imply the backtest returns apply to one stock.

## 9. Secondary sources (cross-check)

Fetched 2026-10-12 by a parallel web pass. "Snippet" = seen only in a search-result
snippet, page not fetched. **Not fetched (403 / fetch failure):** O'Reilly preview
of the book's Appendix A, *Quantitative Value* ch.11, Mauboussin's ROIC PDF, both
alphaarchitect.com pages, gothamfunds.com (formulainvesting.com now 301s there).

| Claim | Independent confirmation | Status |
|---|---|---|
| ROC = EBIT/(NWC + NFA) | Wikipedia *Magic formula investing*: "return on capital = EBIT / (net fixed assets + working capital)"; AAII (Bajkowski, Dec 2011, aaii.com/journal/article/greenblatts-magic-formula): EBIT "divided by tangible investment capital"; undervaluedequity.com reproduces the appendix heading | Confirmed (2+ independent) |
| Excess cash / ST debt / goodwill exclusions | undervaluedequity.com reproduces all three appendix sentences verbatim; stablebread.com: goodwill excluded "as it's a historical cost that doesn't require regular replacement" | Confirmed — but undervaluedequity is a reproduction of the book, not independent evidence |
| EY = EBIT/EV incl. preferred, net debt | AAII 2011: EV computed "by adding market capitalization, preferred stock, and total debt and subtracting excess cash" | Confirmed (AAII); "net interest-bearing debt" wording snippet-only elsewhere |
| TTM earnings | GuruFocus (Engle, 2018): "EBIT is last 12-months' earnings before interests and taxes" | Confirmed; "most recent balance sheet" rests on the book only |
| Utilities / financials / ADRs excluded | Wikipedia: "Exclude utility and financial stocks", "Exclude foreign companies (American Depositary Receipts)" | Confirmed |
| Min market cap | AAII (Scatizzi, Aug 2009): "Greenblatt used a market capitalization floor of $50 million"; magicformulainvesting.com has a "Minimum Market Cap" field | $50M confirmed; **$100M rests on the book (p.134) alone** — secondary sources mention it only in third-party backtests |
| 25% ROA fallback | stablebread.com: ROA "with a minimum of 25%"; AAII 2011 mentions the ROA substitute but no number | Partly confirmed (one secondary source has the 25%) |
| 6% floor | undervaluedequity.com reproduces the p.15 sentence; AAII 2009 compares to the 10-year but gives no 6% floor | Book-only in substance |
| 20–30 stocks, ~1-year hold, tax timing | magicformulainvesting.com *How it works*: "keep at least 20 stocks", "keep your stocks for approximately one year", "sell any losses before the one year holding period is reached" | Confirmed (first-party site) |

**Note on AAII's own screen:** AAII's 2025 screen (aaii.com/stockideas/article/354951)
uses "a return on invested capital greater than 25%" — an AAII choice, not a
Greenblatt number; it should not be cited as Greenblatt's ROC bar.

**Note on the 6% comparisons in the body text:** chapter 2–3 examples (e.g. p.40)
compute earnings yield as earnings per share ÷ share price and compare it with the
6% bond; only the appendix footnote (p.142) specifies after-tax EBIT/EV for that
comparison. The body is a simplification for the reader; the appendix is the
technical definition.

## 10. Known critiques

- **ROC adds little beyond EY (Gray & Carlisle).** CFA Institute *Inside Investing*
  review of *Quantitative Value* (Bochman, 2013-05-16): "the magic formula derives
  all of its "magic" from the cheapness metric (EBIT/EV)". Carlisle (greenbackd.com,
  May 2012): ROC "adds little to the performance of the value metric (EBIT/EV)".
  **Disputed:** the same Carlisle page quotes Montier that the ROC component
  "prevented the massive underperformance" of pure value in Japan. So: "adds
  little" (US sample), not "adds nothing". Primary book chapter not fetched.
- **Negative NWC.** GuruFocus 2018 convention: "If net working capital is negative,
  use zero." Greenblatt is silent. Negative NWC (e.g. subscription businesses,
  retailers with float) inflates ROC or makes the denominator ≤0.
- **Negative / tiny EV.** No written source found. GuruAgents code treats EV ≤ 0 as
  not applicable (observed in code). Greenblatt is silent.
- **Cyclicals at peak.** stablebread.com: may "incorrectly identify cyclical
  companies at peak earnings as high-quality businesses". This is Greenblatt's own
  p.102–104 normal-earnings caveat restated.
- **Post-publication performance.** Mixed and window-dependent: Reasonable
  Deviations (2020-06-08) found a "12% annualised return" vs the benchmark's "13%"
  after 2010; stablebread (2014–2024 test) found it "significantly underperformed
  the S&P 500"; a Valuelytica snippet claims outperformance to 2019. **No clean
  "underperformed 2009–2019" finding** — do not narrate one.

## 11. What open-source single-ticker agents use

Observed via `gh api` on 2026-10-12.

- **FinceptTerminal** (HEAD `3f444cb`, 2026-10-01) — "Joel Greenblatt Magic Formula
  Agent" in `fincept-qt/scripts/agents/TraderInvestorsAgent/configs/agent_definitions.json`
  lines 455–491 (last changed `c0fd843a7e`, 2026-04-18): `"minimum_roc": 0.15`,
  `"minimum_earnings_yield": 0.08`, `"magic_formula_threshold": 70` (lines 487–490).
  Prompt (line 474) adds EV > $500M and three years of positive EBIT, with
  EV = "market cap + total debt - cash" (no preferred, all cash).
  **No source cited for 15% / 8% — unsourced; treat as the authors' choice, not
  Greenblatt's.**
- Fincept's legacy Python agent (fork `tleechan/Fincept-Corporation`,
  `legacy-python-depreciated/.../joel_greenblatt_agent.py`) — banded, not gated:
  EY >6/9/12/15%, ROIC >10/15/20/25%. Defects: cash proxied as
  `current_assets * 0.2` (line 119); invested capital
  `max(working_capital + (total_assets - current_assets), total_assets*0.5)`
  (line 172) keeps goodwill in. Unsourced.
- **yejining99/GuruAgents** `agents/JoelGreenblatt_agent.py` — ROIC =
  EBIT_TTM / ((CA − Cash − CL) + NetPPE), EV ≤ 0 → not applicable; ranks only, no
  thresholds. Closest to the book's definitions.
- **virattt/ai-hedge-fund — no Greenblatt agent** (confirmed: HEAD `78b779c`
  `hedge_fund/signals/` and pre-2.0 `src/agents/` at `6c41ae8` list none; code search
  for "greenblatt"/"magic formula" empty).
- Seen by name only, not inspected: brightbird/agno_ai_investment,
  sou350121/investment-masters-handbook, nlas12/ASIM-LLM-MAS.

**Inference.** Every absolute threshold found in open source is unsourced. The only
Greenblatt-published absolute numbers are the 6% (≥ 10-year) EY hurdle (p.15,
p.103, p.142) and the 25% ROA screener stand-in (p.136).

## 12. Snapshot fit (observed in this repo)

`whale_engine/src/whale_engine/fetch.py` (origin/main `2cd18c6`):

- Present: `operating_income` ← `OperatingIncomeLoss` (TTM flow, line 54);
  `current_assets`, `current_liabilities` (lines 91–92); `cash_and_equivalents`
  (lines 93–96); `long_term_debt` (lines 97–107); short-term debt via `DebtCurrent`
  or component sum (lines 120–125); `outstanding_shares`; `market_cap`.
- Absent: net PP&E (charter's additive field), goodwill, preferred stock,
  marketable securities / short-term investments, income-tax expense / effective
  rate.

**Inference.** `OperatingIncomeLoss` is the natural EBIT proxy but is not identical
to EBIT (it excludes non-operating income; some filers don't tag it). Preferred is
absent, so EV will omit preferred unless a field is added — immaterial for most
names, material for a few.

## Owner quote-check

**Status 2026-10-12: NOT DONE — fallback applied.** The owner holds a 2006 edition
but delegated the check to the agent. The agent cannot verify against a physical
copy, and no local copy or URL of the unofficial PDF was retained from the research
pass, so a re-read was not possible. Every book quote in this doc therefore
**remains UNVERIFIED**. The rubric lock (#108) must treat the "book only" claims
listed at the end of this section as unverified anchors and say so in the review.
The checklist stays for whenever the owner does the read; ticking it is a one-line
amendment, no ticket needed.

Tick each against your own copy; note edition and actual page.

- [ ] p.15 — "whenever the long-term government bond is paying less than 6 percent, we will still assume the rate is 6 percent."
- [ ] p.15 — "if long-term U.S. government bond rates rose to 7 percent or higher, we would use 7 percent or that higher number."
- [ ] p.43–44 — "50 percent return on capital" / "2.5 percent" (illustration)
- [ ] p.53 fn — "certain financial stocks and utilities are excluded from our stock universe"
- [ ] p.102 — "we should be plugging in estimates for earnings in a normal year."
- [ ] p.102 fn — "A normal year is one in which nothing extraordinary or unusual is happening within the company, its industry, or the overall economy."
- [ ] p.103 — "We could then compare the earnings yield based on normal earnings to a risk-free 6 percent government bond and to our other investment opportunities."
- [ ] p.103 — "this is precisely the way my partners and I use the principles behind the magic formula to make our own investment decisions."
- [ ] p.103 — "You have no business investing in individual stocks on your own!"
- [ ] p.104 — "for individual companies, this may not be the case."
- [ ] p.131 — "at least 20 to 30 stocks at one time"
- [ ] p.134 — "above $50 million or $100 million should be of sufficient size" (prior pass said p.135)
- [ ] p.135 — "for a minimum of three to five years, regardless of results."
- [ ] p.136 — "Set the minimum ROA at 25%." / "This will take the place of return on capital from the magic formula study."
- [ ] p.136 — "Eliminate all utilities and financial stocks (i.e., mutual funds, banks and insurance companies)"
- [ ] p.136 — "Eliminate all foreign companies from the list."
- [ ] p.136 — very low P/E "say 5 or less" may mean data "unusual in some way"
- [ ] p.138 — "EBIT/(Net Working Capital + Net Fixed Assets)"
- [ ] p.138 fn — "earnings-related numbers were based on the latest 12-month period, balance sheet items were based on the most recent balance sheet"
- [ ] p.138 fn — "Utilities, financial stocks and companies where we could not be certain that the information in the database was timely or complete were eliminated."
- [ ] p.138 fn — "Adjustments were also made for certain non-interest bearing liabilities."
- [ ] p.139 — "excess cash not needed to conduct the business was excluded from this calculation"
- [ ] p.139 fn — "assumed that EBITDA − Maintenance Cap/Expenditures = EBIT"
- [ ] p.140 — "short-term interest-bearing debt was excluded from current liabilities for this calculation"
- [ ] p.140 NOTE — "Intangible assets, specifically goodwill, were excluded from the tangible capital employed calculations."
- [ ] p.141 — "EBIT/Enterprise Value"; EV = "market value of equity + net interest-bearing debt", fn "Including preferred equity."
- [ ] p.142 fn (charter says p.143) — "fully taxed EBIT to enterprise value" is the ratio compared "versus the risk-free 10-year government bond yield"; 40% tax rate in the example.

If you have no copy, these rest on secondary sources only: ROC/EY formulas and
exclusions (AAII, Wikipedia — confirmed); TTM timing (GuruFocus); 6% floor and the
p.103 single-company rule (only a reproduction site, undervaluedequity.com);
"most recent balance sheet", after-tax-vs-bond (p.142), normal-year definition,
$100M cap, and p.104 "individual companies" caveat (**book only — no secondary
source found**).

## Implications for rubric v1 (open choices for #108 — not decisions)

1. **EY hurdle form.** After-tax EBIT/EV ≥ 6% (p.142 + p.15) vs pre-tax EBIT/EV
   ≥ 6% (looser, simpler). If after-tax: fixed 40% (Greenblatt's example), current
   21% US statutory, or company effective rate (needs a tax field).
2. **Hurdle wording.** Fixed 6% (charter) — document that the book's rule is
   max(6%, 10-year yield) and the constant under-states it if the 10-year exceeds 6%.
3. **ROC bar(s).** No Greenblatt number exists. Options: owner-chosen bar(s);
   borrow the 25% ROA screener figure as a ROC bar (flag as a repurpose); Fincept's
   15% (unsourced); banded tiers. Owner signs whichever.
4. **Excess cash.** None subtracted (all cash in NWC); all cash treated as excess;
   or a rule (e.g. cash above X% of revenue). Same choice affects EV ("net" debt).
5. **Short-term debt.** Remove from current liabilities using the existing
   `DebtCurrent`/component field — matches p.140 with no new data.
6. **Goodwill.** NWC + net PP&E excludes it automatically; decide whether a goodwill
   field is wanted only for narration ("ROC excludes $X goodwill").
7. **Preferred in EV.** Add a preferred-stock field, or omit and document (book says
   include).
8. **Negative / zero NWC and negative / zero EV.** Floor NWC at 0 (GuruFocus), walk
   away, or compute and flag. EV ≤ 0 → walk away vs "cheap" signal.
9. **Normal vs TTM EBIT.** TTM only (book's mechanical formula) vs a guard against
   peak earnings (e.g. TTM vs multi-year average EBIT, positive EBIT in N of M years —
   Fincept uses 3 years). Greenblatt's own p.104 caveat is the justification.
10. **EBIT proxy.** `OperatingIncomeLoss` as-is vs a fallback chain; walk away when
    absent.
11. **Walk-away universe.** Financials (banks, insurers, funds — p.136), utilities;
    decide on REITs/BDCs/brokers (not named). ADR/foreign: EDGAR 20-F filers likely
    lack the snapshot anyway — confirm. Min market cap $50M (or none — single-ticker).
12. **Very-low-multiple data check.** p.136 flags P/E ≤ 5 as possibly bad data —
    optional warning when EY is implausibly high.
13. **Signal shape.** Pass both / pass one / pass neither mapping to
    bullish/neutral/bearish, and confidence cutoffs — no Greenblatt guidance; owner
    judgment.
14. **Persona caveats to pin as strings** (map #80 lesson): single-name use is the
    p.103 "partners" use requiring normal-earnings estimates; backtest returns are
    for ~30-stock baskets held a year; Gray & Carlisle "ROC adds little" (disputed);
    no claim of post-2009 under/out-performance.
