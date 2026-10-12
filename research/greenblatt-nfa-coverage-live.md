# Net fixed assets / goodwill coverage, live check of the 17 uncached tickers

Researched 2026-10-12 (single agent, live SEC read). Resolves #116, part of map #105
(Greenblatt). Extends [`greenblatt-nfa-coverage.md`](https://github.com/philipbergman6-glitch/agents/blob/research/greenblatt-nfa-coverage/research/greenblatt-nfa-coverage.md)
(#107, 6 cached tickers) to the 17 it couldn't check: AAL CAVA CCL CIFR F GM GOOGL HUT IREN
JNJ JPM LULU MA META PG V WULF.

**Live, read-only.** Companyfacts were pulled through edgartools 5.43.0 (`whale_engine/uv.lock`)
with the owner-authorised identity for this session only. No `whale fetch`, no snapshot writes.
All 17 pulls succeeded. Snapshots were read, never written. `MA-2026-07-29.json` was not
touched; the MA preview uses `MA-2026-08-04.json`.

## Answer

- **The charter fallback (`PropertyPlantAndEquipmentNet` → PPE+ROU-after → Gross − Accum)
  resolves NFA at `periods[0]` for 14 of 17.** The three it misses:
  - **GM** has filed no candidate tag since 2023-09-30. It moved to
    `PropertyPlantAndEquipmentExcludingLessorAssetUnderOperatingLeaseAfterAccumulatedDepreciation`
    (53.316B @ 2026-06-30).
  - **IREN** files PPE+ROU-after only in 10-Ks. At the 10-Q date 2026-03-31 only the ROU
    Before − Accumulated pair resolves (4.541B, derived).
  - **JPM** has filed no PP&E tag in companyfacts since 2023-09-30. It's a bank (SIC 6021), so
    it walks away anyway.
- **Both fixed tag orders have stale-value traps in this data:**
  - **PPEN-first traps** (old tag still inside the 135-day window after a switch): F FY2025
    **+20.0%**, HUT FY2023 **−43.9%**, CIFR 2024-09-30 **−23.1%**, GOOGL 2025-06-30 −8.9%,
    META FY2020 −7.3%, AAL FY2020 +1.8%.
  - **ROU-first traps** (10-K-only PPE+ROU beats an exact 10-Q PPEN): MA at every Q1
    (−0.8% to −2.0%), GOOGL Q1 2024 and Q1 2025 (−6.2%, −7.6%), IREN 2025-09-30 (−8.7%),
    CIFR 2024-03-31 (+2.2%), F 2025-03-31 (−1.3%).
  - #107's PPE+ROU-first recommendation is therefore not safe either.
- **Freshest end across tags wins** resolved every pinned window that has an `Assets` instant
  (JPM excepted) at the exact `Assets` date. The candidate set was PPE+ROU, PPEN, GM's
  exclude-lessor tag and the ROU pair. Where two *named* tags share an end, their values were
  identical in all 21 overlapping dates across the 17 tickers. **Derived pairs do not always
  tie out:** GOOGL Gross − Accum runs about 30% below PPEN, and IREN's ROU pair runs 7% above
  PPE+ROU-after at 2026-06-30. So a named tag has to win any tie on the same end.
- **Goodwill:** `Goodwill` resolves at `periods[0]` for 14/17.
  - **CIFR** has never filed it.
  - **GM** stopped tagging it in 2026 10-Qs. Its last value is 2025-12-31, which is outside
    the window, though `IntangibleAssetsNetIncludingGoodwill` 4.305B is filed.
  - **F** files it in 10-Ks only since 2024. Its 2025-12-31 value resolves at 2026-03-31
    because it is 90 days back.
  - In each case, absent means missing, not zero (as with AAPL in #107).
- **SIC:** CIFR, HUT, IREN and WULF are all **6199 "Finance Services"**. A "financials = SIC
  60–67" walk-away would therefore exclude every miner, not just JPM (6021). No ticker is a
  utility (49xx).

## Method

- **Probe:** `edgar.Company(T).facts.query().by_concept(tag).to_dataframe()`, filtered to the
  exact `us-gaap:` concept. This is the same call `_concept_history` makes
  (`whale_engine/src/whale_engine/fetch.py:257-271`).
- **Resolution** re-implements `_balance_at` (`fetch.py:274-298`):
  - instants only
  - the latest `end` in `[window − 135d, window]` (`BALANCE_STALENESS_DAYS`, `fetch.py:138`)
  - on the same end, the latest `filing_date` wins
  - first tag in list order wins (`_build_balance`, `fetch.py:851-873`)
- **Derived pairs** count only when both legs share one `end`, mirroring `fetch.py:877-891`.
- **Window** = newest snapshot's `periods[0].period_end`. For all 17 this equals the `@date` on
  `total_assets` in `tags_used`, so it is the snapshot's balance date.
- **"Latest"** = the newest `Assets` instant in live companyfacts.
- **Trap scan** = every `periods[].period_end` and `annual_periods[].period_end` in that snapshot.
- **SIC:** from the snapshot when it has `sic`. Older snapshots (AAL CCL F GM GOOGL JNJ LULU PG)
  don't have it, so their SIC comes from live `Company.sic` and is marked *(live)*.
- Probe scripts lived in the session scratchpad (not committed). The identity was passed by
  environment variable only.

Rungs: (1) `PropertyPlantAndEquipmentNet`; (2)
`PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization`;
(3) `PropertyPlantAndEquipmentGross` − `AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment`;
(4) PPE+ROU `…BeforeAccumulatedDepreciationAndAmortization` − `…AccumulatedDepreciationAndAmortization`.
(GM) = `PropertyPlantAndEquipmentExcludingLessorAssetUnderOperatingLeaseAfterAccumulatedDepreciation`
(not a charter rung).

## Coverage table (at `periods[0]`)

| Ticker | Snapshot | Date | NFA tag (rung) | NFA | Form / accn | NFA ÷ Assets | Goodwill | IntangExclGW | SIC |
|---|---|---|---|---|---|---|---|---|---|
| AAL | AAL-2026-07-27 | 2026-06-30 | PPE+ROU (2) | 33.082B | 10-Q 0000006201-26-000052 | 51.5% | 4.091B | 2.069B | 4512 *(live)* |
| CAVA | CAVA-2026-08-04 | 2026-04-19 | PPEN (1) | 0.479B | 10-Q 0001628280-26-036625 | 33.7% | 0.002B | 0.002B | 5812 |
| CCL | CCL-2026-07-29 | 2026-05-31 | PPEN (1) | 43.616B | 10-Q 0000815097-26-000096 | 83.5% | 0.579B | 1.181B | 4400 *(live)* |
| CIFR | CIFR-2026-08-12 | 2026-06-30 | PPE+ROU (2) | 2.133B | 10-Q 0001819989-26-000041 | 28.4% | **never filed** | 0.077B | **6199** |
| F | F-2026-07-27 | 2026-03-31 | PPE+ROU (2) | 38.091B | 10-Q 0000037996-26-000086 | 13.5% | 0.483B @2025-12-31 (10-K only) | none | 3711 *(live)* |
| GM | GM-2026-07-27 | 2026-06-30 | **none under charter**; (GM) tag resolves | 53.316B (GM tag) | 10-Q 0001467858-26-000051 | 18.9% | **none in window** (last 2025-12-31) | none (tag ends 2016) | 3711 *(live)* |
| GOOGL | GOOGL-2026-07-28 | 2026-06-30 | PPE+ROU (2) | 321.212B | 10-Q 0001652044-26-000071 | 34.8% | 57.828B | 9.105B | 7370 *(live)* |
| HUT | HUT-2026-08-12 | 2026-06-30 | PPE+ROU (2) | 1.372B | 10-Q 0001104659-26-090025 | 13.8% | 0.208B | 0.009B | **6199** |
| IREN | IREN-2026-08-12 | 2026-03-31 | **none under charter**; rung 4 resolves | 4.541B (derived) | 10-Q 0001878848-26-000026 | 62.5% | 0.001B | none | **6199** |
| JNJ | JNJ-2026-07-27 | 2026-06-28 | PPEN (1) | 23.582B | 10-Q 0000200406-26-000153 | 11.7% | 48.479B | 48.229B | 2834 *(live)* |
| JPM | JPM-2026-08-04 | 2026-03-31 | **none** (PPEN ends 2023-09-30) | — | — | — | 52.706B | none | **6021** |
| LULU | LULU-2026-07-29 | 2026-05-03 | PPEN (1) | 2.046B | 10-Q 0001397187-26-000078 | 24.0% | 0.185B | none | 2300 *(live)* |
| MA | MA-2026-08-04 | 2026-06-30 | PPEN (1) | 2.541B | 10-Q 0001141391-26-000083 | 4.4% | 9.498B | 5.466B | 7389 |
| META | META-2026-08-04 | 2026-03-31 | PPE+ROU (2) | 194.776B | 10-Q 0001628280-26-028526 | 49.3% | 24.748B | 3.692B @2025-12-31 | 7370 |
| PG | PG-2026-07-27 | 2026-03-31 | PPEN (1) | 24.574B | 10-Q 0000080424-26-000060 | 19.1% | 41.359B | 21.531B | 2840 *(live)* |
| V | V-2026-08-04 | 2026-03-31 | PPEN (1) | 4.778B | 10-Q 0001403161-26-000079 | 5.0% | 20.891B | 27.750B | 7389 |
| WULF | WULF-2026-08-12 | 2026-06-30 | PPEN (1) | 3.600B | 10-Q 0001083301-26-000166 | 44.7% | 0.055B | none | **6199** |

**Latest date, where it is newer than `periods[0]`.** The tag is the same as at `periods[0]`
unless noted.

- **CAVA:** 0.507B @ 2026-07-12 (33.8%).
- **CCL:** 43.397B @ 2026-08-31 (85.1%).
- **IREN:** **PPE+ROU (2)** 6.753B @ 2026-06-30, 10-K 0001878848-26-000052 (42.8%).
- **JPM:** still none @ 2026-06-30.
- **LULU:** 2.046B @ 2026-08-02 (24.1%).
- **META:** 225.724B @ 2026-06-30 (50.2%).
- **PG:** 25.360B @ 2026-06-30, 10-K (20.0%).

All other tickers' latest `Assets` date equals `periods[0]`.

## Findings

### 1. Tag switches

| Ticker | PPEN span | PPE+ROU-after span | Note |
|---|---|---|---|
| AAL | 2009-12-31 → 2020-09-30 | 2019-12-31 → 2026-06-30 | ASC 842 switch at FY2020 |
| CIFR | 2021-01-31 → 2024-06-30 | 2023-12-31 → 2026-06-30 | Overlap 2023-12-31 to 2024-06-30. PPE+ROU was 10-K-only at first |
| F | 2008-12-31 → 2025-09-30 | 2024-12-31, 2025-12-31, 2026-03-31 | Switched at FY2025 10-K |
| GM | 2011-12-31 → 2023-09-30 | never | (GM) tag from 2022-12-31 (FY2023 10-K comparative), equal to PPEN at 2022-12-31 (45.248B) |
| GOOGL | 2014-12-31 → 2025-03-31 | 2019-12-31 → 2026-06-30 | Alternates by filing: the 10-Qs for 2024-03-31, 2024-06-30 and 2025-03-31 carry PPEN only, and most other quarters carry PPE+ROU. Uniform on PPE+ROU from 2025-06-30 |
| HUT | 2023-06-30, 2023-09-30 only | 2022-06-30 → 2026-06-30 | Two 10-Qs on PPEN, around the 2023 USBTC merger (*timing inferred*) |
| IREN | 2024-06-30 → 2025-09-30 | 2025-06-30, 2026-06-30 (10-K only) | 10-Qs after 2025-09-30 file only the rung-4 legs. `ifrs-full` facts also present (earlier 20-F era), which the engine ignores |
| JPM | 2008-12-31 → 2023-09-30 | never | No PP&E tag in companyfacts after 2023-09-30 |
| MA | 2008-12-31 → 2026-06-30 | 2019-12-31 → 2025-12-31 (10-K only) | Files both at every year end |
| META | 2011-12-31 → 2020-09-30 | 2019-12-31 → 2026-06-30 | ASC 842 switch at FY2020 |
| CAVA CCL JNJ LULU PG V WULF | through latest | never | PPEN only, no switch |

When both tags carry the same end, the values are equal. That held at all 21 overlapping dates
across 9 tickers (AAL 1, CIFR 1, F 1, GOOGL 7, HUT 1, IREN 1, MA 7, META 1, GM's tag vs
PPEN 1). The #107 "unverified risk", that a dual filer gets the larger finance-lease-inclusive
number, was **not observed**.

### 2. Stale-value traps, by ordering rule

Each row is a pinned window where the first-tag-wins result is not at the `Assets` date. "Error"
is relative to the exact-date value.

**PPEN first (charter order).** The old tag is still within 135 days after a switch.

| Ticker | Window (kind) | Stale value | Exact value | Error |
|---|---|---|---|---|
| F | 2025-12-31 (quarterly **and** annual) | PPEN 44.735B @ 2025-09-30 | PPE+ROU 37.288B | **+20.0%** |
| HUT | 2023-12-31 (annual) | PPEN 0.066B @ 2023-09-30 | PPE+ROU 0.118B | **−43.9%** |
| CIFR | 2024-09-30 (quarterly) | PPEN 0.239B @ 2024-06-30 | PPE+ROU 0.311B | **−23.1%** |
| GOOGL | 2025-06-30 (quarterly) | PPEN 185.062B @ 2025-03-31 | PPE+ROU 203.231B | −8.9% |
| META | 2020-12-31 (annual) | PPEN 42.291B @ 2020-09-30 | PPE+ROU 45.633B | −7.3% |
| AAL | 2020-12-31 (annual) | PPEN 32.256B @ 2020-09-30 | PPE+ROU 31.699B | +1.8% |
| GM | 2023-12-31 (annual) | PPEN 49.399B @ 2023-09-30 | (GM) 50.321B | −1.8% (only if the (GM) tag is listed after PPEN) |
| IREN | 2025-12-31 (quarterly) | PPEN 2.115B @ 2025-09-30 | rung 4 3.207B | −34.0% (only if rung 4 is listed after PPEN) |

**PPE+ROU first (#107's recommendation).** A 10-K-only PPE+ROU year-end value beats an exact
10-Q PPEN.

| Ticker | Window | Stale value | Exact value | Error |
|---|---|---|---|---|
| MA | 2026-03-31, 2025-03-31, 2024-03-31 | PPE+ROU 2.303B / 2.138B / 2.061B @ prior 12-31 | PPEN 2.349B / 2.171B / 2.077B | −2.0% / −1.5% / −0.8% |
| GOOGL | 2025-03-31, 2024-03-31 | 171.036B / 134.345B @ prior 12-31 | PPEN 185.062B / 143.182B | −7.6% / −6.2% |
| IREN | 2025-09-30 | 1.931B @ 2025-06-30 | PPEN 2.115B | −8.7% |
| CIFR | 2024-03-31 | 0.244B @ 2023-12-31 | PPEN 0.239B | +2.2% |
| F | 2025-03-31 | 41.928B @ 2024-12-31 | PPEN 42.471B | −1.3% |

**Freshest end across all candidates.** These were PPE+ROU, PPEN and the (GM) tag, with
rungs 3 and 4 as tie-losers. The result landed on the exact `Assets` date in every window
that has `Assets`, for 16 of 17 tickers. JPM has no candidate after 2023-09-30. CIFR 2020-12-31
also has none, but it is pre-history with no `Assets` either. The only same-end conflicts were
derived-vs-named:

- **GOOGL Gross − Accum vs PPEN:** 99.209B vs 134.345B (2023-12-31), 120.439B vs 171.036B
  (2024-12-31) and 129.421B vs 185.062B (2025-03-31).
  - *Unverified why.* GOOGL's Gross/Accum tags presumably cover a narrower asset set.
  - Either way, **rung 3 must never be trusted for GOOGL**.
- **IREN:**
  - rung 3 vs PPEN: 0.467B vs 0.441B (2024-06-30) and 2.132B vs 2.115B (2025-09-30).
  - rung 4 vs PPE+ROU-after: 7.238B vs 6.753B (2026-06-30, same 10-K).
  - *Unverified why;* possibly impairment or deposits carried in the Before leg.
  - At 2025-06-30 rung 4 ties out (1.931B).

So IREN's 2026-03-31 NFA (4.541B, rung 4) carries an unknown error of possibly about 7%.
**Unverified.**

### 3. Leased-vehicle and lessor assets (GM, F, others)

**GM.**

- `PropertySubjectToOrAvailableForOperatingLeaseNet` ("equipment on operating leases, net")
  appears only in 10-Ks lately: 31.586B @ 2024-12-31 and 33.686B @ 2025-12-31.
- **In 10-Qs the same leased-vehicle figure is tagged `OperatingLeaseRightOfUseAsset`:**
  32.881B @ 2026-06-30, and 30–34B every quarter since 2022-09-30.
- In 10-Ks the same `OperatingLeaseRightOfUseAsset` tag holds GM's lessee ROU of about
  0.9–1.1B.
- At 2025-12-31 both tags read 33.686B.
- So `OperatingLeaseRightOfUseAsset` means different things in different GM forms. Any rubric
  that reads it will get a series that jumps about 30× between 10-Q and 10-K.
- (GM)'s tag name says lessor assets are excluded, so GM's NFA leaves out leased vehicles by
  construction.

**Others.**

- **F:** `PropertySubjectToOrAvailableForOperatingLeaseNet` 28.540B @ 2025-12-31, in 10-Ks only
  since 2024. Nothing at 2026-03-31.
- **JPM:** 20.130B @ 2025-12-31.
- **WULF:** 0.617B @ 2026-06-30 (lessor data-centre assets, *inferred* from the tag; unverified).

**Lessee operating-lease ROU sits outside every NFA candidate.** Examples at `periods[0]`:

- META 23.268B
- GOOGL 17.694B
- AAL 6.919B
- LULU 1.949B
- CCL 1.260B
- CAVA 0.417B

Including it, or the lessor fleets, remains a rubric choice (as in #107).

### 4. Goodwill detail

**Resolves at `periods[0]`:**

- AAL, CAVA, CCL, GOOGL, HUT, IREN (0.001B), JNJ, JPM, LULU, MA, META, PG, V, WULF.
  WULF has filed it only since 2024-12-31.
- **F** resolves only through the 135-day window: 0.483B, 10-K-only since 2024.

**Missing:**

- **CIFR:** no `Goodwill` fact ever.
- **GM:** quarterly `Goodwill` stopped after 2025-12-31 (1.9B there). At 2026-06-30 only
  `IntangibleAssetsNetIncludingGoodwill` (4.305B) is filed.

`IntangibleAssetsNetExcludingGoodwill` is patchy again: absent for F, GM (since 2016), JPM,
LULU, WULF (since 2021) and IREN (10-K only). That matches #107's KO/MSFT finding.

## Rough preview: research preview, not engine output, not for clients

> **Research preview — not engine output, not for clients.** These are hand-assembled from the
> newest pinned snapshot plus the live NFA above. Not golden, not quotable, not a Greenblatt
> signal. The rubric (normal vs TTM EBIT, cash, goodwill, after-tax rate, walk-aways) is not
> locked.

Inputs:

- **EBIT** = `periods[0].ttm.operating_income` (`OperatingIncomeLoss`).
- **NWC** = `current_assets − current_liabilities`.
- **NWCx** = NWC − `cash_and_equivalents` + `short_term_debt`.
- **ROC** = EBIT / (NWC + NFA). **ROCx** uses NWCx.
- **EV** = `market_cap` + `short_term_debt` + `long_term_debt` − `cash_and_equivalents`. A
  missing (None) debt field counts as 0, and is flagged.
- **EY** = EBIT / EV. **EY at** = EY × 0.79 (21% tax).
- All in USD billions.

| Ticker | EBIT | NFA | NWC | NWCx | ROC | ROCx | EV | EY | EY at | Flags |
|---|---|---|---|---|---|---|---|---|---|---|
| AAL | 1.008 | 33.082 | −12.480 | −10.647 | 4.9% | 4.5% | 36.669 | 2.7% | 2.2% | negative NWC |
| CAVA | 0.065 | 0.479 | 0.277 | −0.019 | 8.6% | 14.1% | 7.213 | 0.9% | 0.7% | debt fields None (snapshot `debt_unresolved`) |
| CCL | 4.464 | 43.616 | −8.942 | −9.714 | 12.9% | 13.2% | 60.941 | 7.3% | 5.8% | negative NWC |
| CIFR | −0.531 | 2.133 | 2.753 | 2.110 | −10.9% | −12.5% | 11.947 | −4.4% | −3.5% | **negative EBIT; SIC 6199** |
| F | −7.159 | 38.091 | 9.650 | −7.999 | −15.0% | −23.8% | 39.611 | −18.1% | −14.3% | **negative EBIT; short- and long-term debt None → EV excludes all debt (Ford Credit)**; leased vehicles excluded |
| GM | 1.815 | 53.316 (GM tag) | 13.174 | −6.960 | 2.7% | 3.9% | 54.610 | 3.3% | 2.6% | **NFA not charter-resolvable; debt None → EV excludes all debt (GM Financial)**. With leased vehicles (+32.881B): ROC 1.8% / ROCx 2.3% |
| GOOGL | 147.628 | 321.212 | 217.413 | 163.501 | 27.4% | 30.5% | 4038.060 | 3.7% | 2.9% | — |
| HUT | −0.939 | 1.372 | 6.719 | 6.485 | −11.6% | −11.9% | 10.709 | −8.8% | −6.9% | **negative EBIT; SIC 6199**; debt None |
| IREN | −0.408 | 4.541 (rung 4) | 1.773 | −0.440 | −6.5% | −10.0% | 12.145 | −3.4% | −2.7% | **negative EBIT; SIC 6199; NFA not charter-resolvable**; LTD is finance-lease only (0.152B) vs total liabilities 4.600B → EV likely understated *(inference)* |
| JNJ | 21.767 | 23.582 | 4.879 | −3.851 | 76.5% | 110.3% | 663.381 | 3.3% | 2.6% | — |
| JPM | — | — | — | — | — | — | — | — | — | **SIC 6021 bank**; no EBIT, current assets, current liabilities or NFA in snapshot/live; not computable |
| LULU | 2.049 | 2.046 | 2.200 | 0.686 | 48.3% | 75.0% | 11.533 | 17.8% | 14.0% | LTD None (consistent with no funded debt; *unverified*) |
| MA | 20.465 | 2.541 | 1.518 | −7.314 | 504.2% | **capital −4.773 → degenerate** | 516.948 | 4.0% | 3.1% | asset-light: ROC explodes; cash-excluded capital ≤ 0 |
| META | 88.593 | 194.776 | 63.012 | 39.586 | 34.4% | 37.8% | 1511.048 | 5.9% | 4.6% | short-term debt None |
| PG | 20.153 | 24.574 | −10.248 | −9.380 | 140.7% | 132.6% | 367.979 | 5.5% | 4.3% | negative NWC |
| V | 26.296 | 4.778 | 2.549 | −8.296 | 358.9% | **capital −3.518 → degenerate** | 664.084 | 4.0% | 3.1% | asset-light: ROC explodes; cash-excluded capital ≤ 0 |
| WULF | −0.414 | 3.600 | −0.957 | −3.434 | −15.6% | −249.5% (capital 0.166) | 8.941 | −4.6% | −3.7% | **negative EBIT; SIC 6199; negative NWC; near-zero cash-excluded capital** |

What the rubric lock should see (observations, not decisions):

- **Asset-light (V, MA).** ROC is in the hundreds of percent, and goes negative-capital once
  cash is stripped. Any ROC bar is passed trivially, and the cash treatment decides whether
  capital is even positive.
- **Negative NWC** is common outside the asset-light pair: AAL, CCL, PG, WULF, and most names
  under NWCx. Clamping NWC at 0, as Greenblatt's book is often read to do, would change ROC
  materially for PG and CCL. *That reading of the book is unverified here; owner check against
  the book.*
- **Captive finance (F, GM).** Snapshots carry no debt, so EV excludes tens of billions of
  finance-arm debt. NFA also excludes the leased fleets. ROC and EY here are not meaningful
  without a walk-away or a rubric choice.
- **Miners (CIFR, HUT, IREN, WULF).** All have negative TTM EBIT, all are SIC 6199, and all
  have missing or partial debt. They walk away on EBIT ≤ 0 alone, and also on a 60–67 SIC rule
  if adopted.
- **The 6% hurdle.** Only LULU's after-tax EY (14.0%) clears the charter's 6% hurdle. CCL
  (5.8%) is close.

## Implications for #108 / the fields ticket (options, not decisions)

1. **Tag order alone can't be made safe.** Each fixed order fails on real pinned windows: F,
   HUT and CIFR one way; MA, GOOGL and IREN the other. *Freshest end across the field's tags*,
   with named tags beating derived ones on a tie, fixed every observed case. The alternative
   is to keep first-hit-wins but require an exact match with the `total_assets` end date and
   fall through otherwise. That is also consistent with every observation here, but untested
   as a rule.
2. **Add the (GM) tag**
   (`PropertyPlantAndEquipmentExcludingLessorAssetUnderOperatingLeaseAfterAccumulatedDepreciation`)
   if GM should be scorable. It is a tag outside the charter's list.
3. **Rung 4 (ROU Before − Accum)** is needed for IREN 10-Q dates. It disagrees with the named
   tag by 7% on the one 10-K date where both exist. Adding it trades a walk-away for a possibly
   inexact number.
4. **Rung 3 (Gross − Accum)** was never the only resolver for any of the 17, and is wrong for
   GOOGL. Evidence from 23/23 tickers now says drop it.
5. **Goodwill:** `Goodwill` alone, absent ≠ 0. That covers CIFR (never), GM (stopped
   quarterly) and F (annual only).

## Unverified / open

- Why GOOGL's Gross − Accum and IREN's rung 4 don't tie to the named tags. No filing text was
  read.
- Whether JPM tags premises and equipment under a company-extension concept. Companyfacts
  carries no extensions, so the engine can't see one either way.
- Whether `long_term_debt` hits the same stale-tag pattern (not checked, as in #107).
- Snapshot debt gaps (F, GM, HUT, CAVA, IREN, META) were taken as found. Whether they are real
  zeros or tag misses was not checked against filings.

## Sources

- Live SEC companyfacts via edgartools 5.43.0, pulled 2026-10-12. CIKs: AAL 6201, CAVA
  1639438, CCL 815097, CIFR 1819989, F 37996, GM 1467858, GOOGL 1652044, HUT 1964789, IREN
  1878848, JNJ 200406, JPM 19617, LULU 1397187, MA 1141391, META 1326801, PG 80424, V 1403161,
  WULF 1083301. Accession numbers are cited per row.
- `whale_engine/src/whale_engine/fetch.py` at `2cd18c6`:
  - `BALANCE_TAGS` at 84-113
  - `BALANCE_STALENESS_DAYS` at 138
  - `_concept_history` at 257-271
  - `_balance_at` at 274-298
  - `_build_balance` at 851-892
- Snapshots (read-only): `whale_engine/snapshots/{AAL-2026-07-27, CAVA-2026-08-04,
  CCL-2026-07-29, CIFR-2026-08-12, F-2026-07-27, GM-2026-07-27, GOOGL-2026-07-28,
  HUT-2026-08-12, IREN-2026-08-12, JNJ-2026-07-27, JPM-2026-08-04, LULU-2026-07-29,
  MA-2026-08-04, META-2026-08-04, PG-2026-07-27, V-2026-08-04, WULF-2026-08-12}.json`.
- Prior offline findings: branch `research/greenblatt-nfa-coverage` @ `22a708f`.
