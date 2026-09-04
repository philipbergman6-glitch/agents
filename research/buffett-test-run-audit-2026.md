# Test-run audit: tracing every number in live Buffett diagnoses

Audit of the first Buffett test runs across a spread of company shapes.
Evidence base for the validation layer: what the engine's numbers actually
rest on, observed on live EDGAR data, 2026-07-26 → 2026-07-28.

## Method

Six tickers spanning the archetypes the ticket named, fetched with `uv run buffett fetch`
(edgartools via `EDGAR_IDENTITY`), diagnosed with `uv run buffett diagnose` (rubric v2):

| Ticker | Archetype | Snapshot | Diagnosis outcome |
|---|---|---|---|
| META | calendar-FY mega-cap | `META-2026-07-28.json` | bearish 80, 18/22 (pricing_power excluded) |
| GOOGL | multi-class, 2022 20:1 split | `GOOGL-2026-07-28.json` | bearish 90, 19/22 (pricing_power excluded, 5 annual periods dropped) |
| JPM | bank | `JPM-2026-07-28.json` | **hard-fail**: `MissingDataError: only 0 complete periods` |
| LULU | off-cycle FY (Feb, 53-wk retail) | `LULU-2026-07-27.json` | bullish 93, 24/27 |
| CAVA | recent IPO (2023) | `CAVA-2026-07-27.json` | bearish 75, 11/27, negative owner earnings |
| NVDA | Jan FY, two splits (4:1 '21, 10:1 '24) | `NVDA-2026-07-26.json` | bearish, 21/27, **7/10 annual periods dropped** |

Every field in each snapshot was joined against its `tags_used` provenance entry and
classified: companyfacts (direct XBRL tag), filing-fallback, proxy, derived, sum-of-parts,
or None. Diagnoses were then checked for how each gap/fallback propagated into scores.
All numbers below are quoted from the snapshot/diagnosis JSON — none are estimated.

## Source census (observed, not theoretical)

Across all six snapshots (~20 fields × 10 quarterly + up to 10 annual periods each):

- **companyfacts XBRL is the overwhelming source** — every flow and balance value that
  resolved came from the tag-fallback lists; the per-filing XBRL fallback (`filing-fallback:`)
  fired **zero times** in this set (no MSFT-style extension-tag D&A, no cover-page share sums).
- **Proxy shares** (`proxy:WeightedAverageNumberOfSharesOutstandingBasic`): META all 20
  periods; CAVA 1 annual period. META exposes no point-in-time share count in companyfacts.
- **Derived / sum-of-parts**: GOOGL & JPM short_term_debt from component sums
  (`CommercialPaper+LongTermDebtCurrent`, `ShortTermBorrowings+CommercialPaper`); no
  ticker needed the `LiabilitiesAndStockholdersEquity − equity` derivation.
- **Mixed tags across history** (fallback order changing mid-series, by design):
  GOOGL revenue `Revenues`→`RevenueFromContractWithCustomerExcludingAssessedTax`;
  LULU revenue `SalesRevenueNet` pre-2018; GOOGL long_term_debt `LongTermDebt`↔
  `LongTermDebtNoncurrent`; JPM/LULU/CAVA cash `…AtCarryingValue`↔`…RestrictedCash…`
  (these two tags have *different definitions* — restricted-cash-inclusive vs not — so a
  mid-series switch is a real discontinuity, not just a rename).
- **market_cap: yfinance `fast_info.market_cap` for all six.** The only non-EDGAR number
  in every snapshot, and the denominator of margin-of-safety — the signal's second axis.

## (a) Values resting on a single fragile path

1. **market_cap — yfinance, no cross-check, no alternative.** Hard-fails honestly when
   yfinance breaks (good), but there is no validation of the value it *does* return: a
   plausible-but-wrong market cap flips signal (MoS boundary at −0.30 and 0) with no way
   to notice. Confirms the market-cap-sourcing premise; note a shares×price rebuild has EDGAR share
   counts available in the same snapshot to sanity-check against.
2. **edgartools `get_ttm()` stitching — trusted for every quarterly flow value.** All six
   tickers' quarterly TTMs carry the edgartools warning *"Some quarters were derived from
   YTD or annual facts. These are calculated values, not directly reported"* — i.e. the
   ~2.5y quarterly window is essentially never raw filed data; it is edgartools arithmetic.
   CAVA's warning escalates to *"Gaps detected in quarterly data. TTM calculation may not
   be accurate"* on 6 of 10 windows. Nothing downstream reads these warnings (see b-1).
3. **The warning is only captured for net_income.** `fetch.py` records
   `m.has_gaps or m.warning` inside the `field == "net_income"` branch only; revenue, capex,
   D&A TTMs from the same stitcher lose their warnings entirely — not even the snapshot
   knows.
4. **META's proxy share path has no cross-check.** The cover-page fallback validates its sum
   against yfinance (`SHARES_MISMATCH_FACTOR` 1.4, hard-fail). The weighted-average-basic
   *proxy* path — which supplied 100% of META's share counts — has no reference check at
   all, and it feeds BVPS in a 5/5-scored dimension.
5. **Annual D&A backfill is conditional on quarterly gaps.** The per-filing fallback for
   annual-period D&A only runs `if missing_dna` — computed from the *quarterly* array.
   GOOGL: quarterly D&A complete → fallback never attempted → annual D&A None for
   2016-2020 (5/10 fiscal years) with no route to fill it. Harmless today (D&A isn't in
   the annual-consuming dimensions) but it silently marks those years incomplete.

## (b) Silent gaps and score distortions

1. **Stitched-TTM warnings never reach the diagnosis.** The `net_income_warning` lands in
   `tags_used` and stops there — `diagnose` flags say nothing. A CAVA client reads a clean
   bearish-75 diagnosis whose TTM inputs edgartools itself labeled "may not be accurate."
   This is the largest honest-failure-mode gap found: the data layer *knows* and the output
   doesn't. (validation layer: promote to a diagnosis flag, or a validation severity tier.)
2. **NVDA: the share-outlier filter dropped the truth and kept the artifact.** The 3×-median
   filter assumes outliers are mistakes. With NVDA's two splits, the 10-year annual window
   holds three cohorts (~0.6B / ~2.5B / ~24.5B shares); the median lands in the *middle*
   cohort and the filter excluded **the three most recent fiscal years** (24.3-24.6B,
   post-10:1-split — the *correct* current counts) plus the four oldest, flagging each as
   "split artifact or mis-tagged fact". BVPS is then judged on 2021-2023 only, and scored
   5/5. Flagged, so not strictly silent — but the flag text asserts the wrong diagnosis of
   which cohort is corrupt. (validation layer: split-aware normalization, not majority-cohort exclusion.)
3. **Banks are out-of-model and the failure mode is one tag away from silent.** JPM misses
   gross_profit, operating_income, capital_expenditure, current_assets/liabilities,
   long_term_debt — all structurally absent from bank income statements/balance sheets, all
   None in all 20 periods. Diagnosis hard-fails **only because capex is on the mandatory
   list**; the error names just `capital_expenditure`. Were capex ever tagged (some banks do
   file PP&E purchases), JPM would diagnose with operating_margin/current_ratio/ROIC each
   "unavailable, scored 0" and moat/pricing_power partly excluded — a structurally
   inapplicable rubric wearing a low score, not an error. (validation layer: detect financial-sector
   filers explicitly; fail with "rubric does not apply", not a missing-tag message.)
4. **None-vs-zero conflation penalizes debt-free filers.** CAVA has no borrowings, so no
   debt tag exists → `debt_to_equity` is None → "Debt/equity unavailable (+0)", losing 2
   fundamentals points for the *most Buffett-approved* debt posture. The scorer's own
   docstring draws the None-vs-0.0 distinction, but absence-of-tag arrives as None, and
   EDGAR has no way to say "0 debt" — untagged and unlevered look identical at the snapshot
   layer. Same shape: LULU long_term_debt None ×20, META short_term_debt None ×20 (both
   truly debt-free on that line; both correctly still scored via the other component — but
   only because *one* debt line happened to resolve).
5. **Growth-capex heuristic can push owner earnings negative and it feeds the DCF as-is.**
   CAVA: net income +$61.6M, D&A $78.3M, but maintenance capex estimated at $145.7M (85% of
   total capex — nearly all of which is new-store growth capex) → owner earnings −$14.5M →
   intrinsic value **−$168M** → MoS −1.02 → bearish. Deterministic and faithful to
   the upstream ai-hedge-fund heuristics, but a negative-intrinsic-value output is presented with the same confidence
   arithmetic as any other. (validation layer / audit consumer: at minimum flag OE<0 explicitly.)
6. **`tags_used` keys don't match the value keys they describe.** Values are stored under
   post-rename names (`dividends_and_other_cash_distributions`,
   `issuance_or_purchase_of_equity_shares`) while provenance stays under pre-rename names
   (`dividends_paid`, `share_issuance`, `share_repurchase`). A mechanical field→provenance
   join — the exact operation a validation layer or auditor performs — silently reports
   these fields as unattributed. (This audit initially mis-counted META's dividends as
   missing for precisely this reason.) Cheap fix, high traceability value.
7. **Legit-absence vs gap is undecidable for zero-if-absent fields.** LULU pays no
   dividends (true) and CAVA has never bought back stock (true); both arrive as None,
   identical to a lost tag. Zero-if-absent is the right rubric default, but the snapshot
   records no distinction for a validator to check.
8. **Truthiness filters drop exact-zero data points.** `analyze_consistency` filters
   `if p["ttm"].get("net_income")` and `analyze_book_value` filters truthy equity/shares —
   a period with net income exactly 0.0 vanishes from the series rather than counting as a
   (terrible) data point. Not observed firing on these six; noted from the trace as a
   latent edge.

## (c) Observed anomalies

- **Split discontinuities in share counts** (annual windows): GOOGL 0.675B→13.24B
  (×19.6, 20:1 split 2022 — pre-split years excluded by the filter, correctly this time,
  shrinking BVPS history to 2021-2025); NVDA as in (b-2); CAVA 1.4M→113.7M (×80.7,
  pre-IPO unit conversion — correctly excluded). The same filter produced one correct,
  one correct-but-history-halving, and one wrong outcome across three tickers.
- **Balance staleness within tolerance but material**: JPM Q1 windows carry
  year-end share counts (90d lag); CAVA's oldest quarterly window carries balances 112
  days stale (FY2022 year-end against an April 2023 window). All within the 135-day
  allowance; ratios mix a Q1 flow numerator with a prior-year-end denominator.
- **Retail 52/53-week calendars behave correctly**: LULU/CAVA period_ends land on
  off-month dates (2026-05-03, 2026-04-19) and annual anchoring tracked them; no
  misalignment observed — the `_ANNUAL_DAYS`/`_END_MATCH_DAYS` windows held.
- **CAVA real growth reads as anomaly**: NI ×3.06 window-over-window and ×9.81
  year-over-year are genuine hypergrowth+IPO-cost effects, not data errors — a reminder
  that scale-jump checks in the validation layer need a legit-hypergrowth escape hatch.
- **gross_profit is structurally absent for non-retail mega-caps** (META, GOOGL, JPM
  never file `GrossProfit`) → pricing_power excluded → their score is x/22 not x/27.
  Renormalization behaves as designed and is flagged; worth knowing that the flagship
  tickers a client will try first all run on the reduced rubric.
- **Fresh-quarter lag asymmetry**: GOOGL's latest window ends 2026-06-30 but
  META/JPM/NVDA stop a quarter earlier — TTM freshness varies ~90 days across same-day
  fetches depending on filing timing. Cross-ticker comparisons quietly compare different
  as-of dates.

## What this means for the validation layer

Priority order this evidence supports:

1. Surface stitched-TTM warnings (all fields, not just net income) into diagnosis flags — the
   engine already holds the signal; it just drops it. (b-1, a-3)
2. Market-cap cross-check vs EDGAR shares × price once market-cap sourcing lands its price source; until
   then even `market_cap / (shares × any recent price)` bounds would catch order-of-magnitude
   errors. (a-1)
3. Split-aware share-count normalization to replace majority-cohort exclusion. (b-2)
4. Sector applicability guard: structural-absence pattern (no opex/capex/current accounts)
   → "rubric not applicable to financial-sector filers", not a missing-tag error. (b-3)
5. `tags_used` key alignment + a "legitimately zero vs missing" marker where EDGAR absence
   is semantic. (b-6, b-4, b-7)
6. Invariant checks the census shows are safe to enforce (balance-sheet identity when both
   sides present, sign conventions, scale continuity with a hypergrowth escape hatch). (c)

Snapshots audited are committed alongside this file under `whale_engine/snapshots/`.
