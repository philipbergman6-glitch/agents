# Net fixed assets / goodwill XBRL coverage across pinned tickers

Researched 2026-10-12 (single agent, offline). Resolves #107, part of map #105 (Greenblatt).
Question: can every pinned ticker supply **net fixed assets** (and goodwill) from EDGAR
XBRL, and under which tag?

**No live SEC calls.** Every value below comes from companyfacts JSON already on disk.
The question can only be answered for **6 of 23 tickers**, because those are the only
companyfacts files cached locally. The other 17 are unverified. See
[Cache coverage](#cache-coverage-the-binding-limit).

## Answer

- **For the 6 tickers with a cache, NFA resolves at both the latest cached balance date
  and the snapshot's `periods[0]` date.** (Those two dates are the same for all 6.) Five
  use `PropertyPlantAndEquipmentNet`. MU uses
  `PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization`.
  None of them needs the Gross − Accum derivation.
- **One real tag switch: MU at ASC 842 adoption** (FY2020 10-K). Combined with the
  engine's first-tag-wins rule and its 135-day staleness window, a PPEN-first order would
  silently take a **stale Q3 value for MU FY2020**, and FY2020 is inside MU's pinned
  `annual_periods`.
- **Goodwill: only `Goodwill` resolves.** AAPL stopped filing it after 2017-12-30, so AAPL
  goodwill is *missing*, not zero.
- **17 tickers cannot be checked offline**, including every name the issue flagged as
  interesting (GM, F, V, MA, JPM, the miners).

## Cache coverage (the binding limit)

Searched locations (a filesystem walk for any file containing
`PropertyPlantAndEquipmentNet` under `~/Documents/Coding_Projects`, `~/Downloads`,
`~/.edgar` and `~/.cache`):

| Cache | CIKs (pinned tickers in **bold**) |
|---|---|
| `~/.edgar/_tcache/data.sec.gov/api-xbrl-companyfacts-CIK0000021344.json` (gzip; meta `fetched` = 2026-10-12 17:27 local) | **KO** |
| `~/Documents/Coding_Projects/ai-hedge-fund/.edgar_cache/CIK*.json` (mtimes 2026-07-24 to 07-28) | **KO**, **AAPL**, **MU**, **MSFT**, **NVDA**, **BLDR**; also TSM (1046179) and 1577552, neither pinned |

- `~/.edgar/_tcache/` also holds `submissions-CIK*.json` for 24 CIKs and 228 cached KO
  filing `.txt` files. Submissions JSON carries no XBRL facts.
- **Not covered (17):** AAL, CAVA, CCL, CIFR, F, GM, GOOGL, HUT, IREN, JNJ, JPM, LULU, MA,
  META, PG, V, WULF.
- The two KO copies agree. Both top out at 2026-04-03 and give the same PPEN and Goodwill
  values from accession 0001628280-26-028802. I don't know why the copy fetched on
  2026-10-12 has no later quarter.
- **Snapshots carry no `cik` field.** Top-level keys are `annual_periods, fetched_at,
  market_cap, market_cap_source, periods, schema_version, source, ticker`. Tickers were
  mapped to CIKs through SEC's `company_tickers.json` cached at
  `ai-hedge-fund/.edgar_cache/company_tickers.json`.

## Coverage table

Method: the probe re-implements `fetch._balance_at` (`whale_engine/src/whale_engine/fetch.py:274-298`)
on raw companyfacts:

- It reads USD instants only.
- It takes the latest `end` in `[window_end − 135d, window_end]`. When the same end is
  filed more than once, the latest `filed` wins.
- The first tag in order with a hit wins.
- A derived pair must share one `end`, which mirrors the liabilities derivation at
  `fetch.py:887-891`.

Window = the snapshot's `periods[0].period_end`. For all 6 tickers this equals the latest
`Assets` instant in the cache, so one row covers both dates.

| Ticker | Date | NFA tag (rung) | NFA | Form / accn | NFA ÷ Assets | Goodwill | IntangibleAssetsNetExclGoodwill | Flags |
|---|---|---|---|---|---|---|---|---|
| AAPL | 2026-03-28 | `PropertyPlantAndEquipmentNet` (1) | 50.116B | 10-Q 0000320193-26-000013 | 13.5% | **none** (last 2017-12-30) | 25.797B | Gross 127.557B − Accum 77.441B = 50.116B (same end, ties out) |
| BLDR | 2026-03-31 | `PropertyPlantAndEquipmentNet` (1) | 2.155B | 10-Q 0001193125-26-195140 | 19.1% | 4.140B | 1.113B | Gross/Accum filed annually only (10-K; none in 10-Qs since 2023) |
| KO | 2026-04-03 | `PropertyPlantAndEquipmentNet` (1) | 9.522B | 10-Q 0001628280-26-028802 | 9.1% | 15.411B | none (tag unused) | Accum tag ends 2019-12-31 (now `PropertyPlantAndEquipmentOwnedAccumulatedDepreciation`), so Gross − Accum never resolves after 2019. 1.95B of PP&E sits in `DisposalGroupIncludingDiscontinuedOperationPropertyPlantAndEquipment` (held for sale, outside PPEN) |
| MSFT | 2026-03-31 | `PropertyPlantAndEquipmentNet` (1) | 283.228B | 10-Q 0001193125-26-191507 | 40.8% | 119.661B | none (tag only filed 2009-06 to 2010-03) | Gross 394.951B − Accum 111.723B = 283.228B (ties out). Operating-lease ROU of 24.40B sits outside every candidate |
| MU | 2026-05-28 | `PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization` (2) | 56.426B | 10-Q 0000723125-26-000015 | 42.1% | 1.150B | 0.473B | **Tag switch at ASC 842.** PPEN last filed 2020-05-28. ROU gross 124.991B − ROU accum 68.565B = 56.426B (ties out) |
| NVDA | 2026-04-26 | `PropertyPlantAndEquipmentNet` (1) | 12.403B | 10-Q 0001045810-26-000052 | 4.8% | 20.894B | 3.120B | Gross/Accum filed annually only (17 × 10-K, 0 × 10-Q) |
| AAL CAVA CCL CIFR F GM GOOGL HUT IREN JNJ JPM LULU MA META PG V WULF | — | **no cache** | — | — | — | — | — | Unverified |

The "rung" column refers to the position in the candidate list:

1. `PropertyPlantAndEquipmentNet`
2. the after-accumulated-depreciation PPE+ROU tag
3. `PropertyPlantAndEquipmentGross` − `AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment`
4. the ROU-combined Before − AccumulatedDepreciation pair

Derived values shown in Flags are coverage cross-checks, not scoring inputs.

All six NFA ÷ Assets ratios look plausible for their business models:

- NVDA, at 4.8%, is fabless.
- MU (42.1%) and MSFT (40.8%) are capex-heavy: fabs for MU, datacenters for MSFT.

## Findings

### 1. History and annual-only reporting

For each 10-K fiscal-year-end `Assets` instant in the cache, the probe recorded which rung
resolved and whether the hit was exactly at that FY end:

- **AAPL** FY2011–FY2025, **BLDR** FY2011–FY2025, **KO** FY2009–FY2025, **MSFT**
  FY2010–FY2025, **NVDA** FY2010–FY2026: PPEN, exact match every year. AAPL has no PPEN
  before 2011-09-24, which is outside the 10-year `N_ANNUAL_PERIODS` window
  (`fetch.py:145`).
- **MU**: PPEN FY2011–FY2019 (exact), **FY2020 (2020-09-03): PPEN, not exact**, then
  PPE+ROU FY2021–FY2025 (exact).
- Annual-only filing: no covered ticker files its *resolving* tag annual-only. Each one
  has 11 or 12 10-Q instants since 2023. Only the rung-3 inputs are annual-only (BLDR,
  KO's gross, NVDA). Rung 3 would therefore hit only at year-end windows, or up to 135
  days after one.

### 2. The MU FY2020 stale-value hazard (engine semantics, observed in data)

MU's PP&E history, read from `ai-hedge-fund/.edgar_cache/CIK0000723125.json`:

```
PropertyPlantAndEquipmentNet   2020-05-28  30,081,000,000  10-Q  filed 2020-06-29  0000723125-20-000067   <- last PPEN fact
PPE+ROU (after accum)          2019-08-29  28,240,000,000  10-K  filed 2020-10-19  (comparative; equals PPEN 28,240,000,000 for the same date)
PPE+ROU (after accum)          2020-09-03  31,031,000,000  10-K  filed 2020-10-19  0000723125-20-000082
```

`MU-2026-07-28.json` `annual_periods` ends include `2020-09-03`.

- With PPEN listed first, `_balance_at(PPEN, 2020-09-03)` returns 30.081B @ 2020-05-28.
  That date is 98 days back, inside the 135-day window, and the PPE+ROU year-end value is
  never consulted.
- The FY2020 NFA would be about 3% low, and the only trace would be the `@2020-05-28`
  suffix in `tags_used`.
- Ordering PPE+ROU first resolves 31.031B at the exact year end.
- The two tags agree at the overlap date (2019-08-29). PPE+ROU-first therefore changes no
  earlier MU value.

This is the same latent pattern as any multi-tag `BALANCE_TAGS` list (`fetch.py:84-113`).
Whether `long_term_debt` hits it anywhere is *not* checked here.

### 3. Goodwill

- `Goodwill` is the only goodwill tag that resolves. At `periods[0]` it resolves for
  BLDR, KO, MSFT, MU and NVDA.
- **AAPL has no `Goodwill` fact after 2017-12-30.** Under `_balance_at` it returns None.
  The rubric has to decide whether None means missing (renormalize or walk away) or zero.
- PPEN and PPE+ROU exclude goodwill by definition. A Greenblatt-style tangible capital of
  NWC + NFA therefore needs goodwill **only** if the rubric derives fixed capital from a
  broader total, for example Assets minus current assets.
- `IntangibleAssetsNetExcludingGoodwill` is patchy: none for KO, none for MSFT after 2010.
  It isn't usable as a general field without more fallbacks.

### 4. edgartools' own standardization is not a safe shortcut

The pinned library is **edgartools 5.43.0** (`whale_engine/uv.lock`), and its
`edgar/xbrl/standardization/gaap_mappings.json` contains these mappings:

- `PropertyPlantAndEquipmentNet` covers 5,604 filers (occurrence rate 0.623).
- The PPE+ROU after-accumulated tag covers 657 filers (rate 0.073), with a `first_year` of
  2021. Both map to `PlantPropertyEquipmentNet`.
- It also maps the **accumulated-depreciation** ROU tag
  (`…AccumulatedDepreciationAndAmortization`) to `PlantPropertyEquipmentNet`, which is
  wrong.
- It maps several indefinite-lived intangibles (trademarks, franchise rights) to
  `Goodwill`.
- It maps `PropertySubjectToOrAvailableForOperatingLeaseNet` to `Inventories`
  (confidence 0.5). That is the tag that matters for GM and F (see below).

So the engine should keep its exact-tag lists, as it already does in
`_concept_history` (`fetch.py:257-271`). Standardized statements shouldn't be used here.

### 5. Uncovered names (hypotheses, unverified because there is no cache)

These come from general knowledge and were *not* observed in data:

- **GM and F:** leased vehicles are expected under a separate
  `PropertySubjectToOrAvailableForOperatingLeaseNet` ("net investment in operating
  leases"), outside PPEN. PPEN-only NFA would leave those out.
- **V and MA:** NFA is expected to be small (asset-light), which makes ROC large and
  sensitive to the denominator.
- **JPM:** a financial company. Greenblatt excludes financials anyway.
- **CCL, CIFR, HUT, IREN, WULF:** PP&E-heavy (ships, miners, datacenters).
  Finance-lease and ROU tagging is unknown.

All of these need checking on the next networked `fetch`, which needs `EDGAR_IDENTITY`.

## Recommended fallback order (an option, not a decision)

The candidate list, written the way `BALANCE_TAGS` expresses fallbacks (ordered,
first-hit-wins, `fetch.py:84`):

```python
"net_fixed_assets": [
    "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
    "PropertyPlantAndEquipmentNet",
],
"goodwill": ["Goodwill"],   # only if the rubric needs it; None = missing, not 0
```

- **Why PPE+ROU first:** it is the post-ASC-842 tag. Putting it first fixes the MU FY2020
  case without changing any earlier MU value, because the two tags are equal at the
  overlap date. None of the other 5 covered filers ever files it, so they are unaffected.
  - *Unverified risk:* a filer that files both tags for the same date would get the
    larger, finance-lease-inclusive number. No covered ticker does this.
- **Alternative rules,** if first-hit-wins feels too brittle at tag switches:
  - *Freshest end across tags wins* for this field. This is general and fixes switches in
    either direction, but it is a change to the resolution semantics.
  - *Exact-FY-end required on the annual path.* This is stricter and could produce None
    where a 10-K files a balance a day off.
- **Derived rung (Gross − Accum, same end):** never needed for the 6 covered tickers.
  It's annual-only for BLDR, KO and NVDA and broken for KO after 2019. Adding it is
  speculative until an uncovered ticker shows it is needed.
- **Open rubric choices this surfaces (not data questions):**
  - whether to include operating-lease ROU (MSFT 24.40B)
  - whether to include held-for-sale PP&E (KO 1.95B)
  - whether to add `PropertySubjectToOrAvailableForOperatingLeaseNet` for GM/F

## Sources

- `whale_engine/src/whale_engine/fetch.py`:
  - `BALANCE_TAGS` at 84-113
  - `BALANCE_STALENESS_DAYS` at 138
  - `_concept_history` at 257-271
  - `_balance_at` at 274-298
  - `_build_balance` at 851-892
- `whale_engine/snapshots/{TICKER}-{latest}.json`: `periods[0].period_end` and
  `annual_periods[].period_end`.
- Companyfacts caches as listed above. Accession numbers are cited per row.
- edgartools 5.43.0 `gaap_mappings.json` (uv cache `archive-v0/zs_0gqPi7aRtGFUs`).
- The probe scripts ran with `python3 -I` from the session scratchpad over the cache paths
  and were not committed. To reproduce, re-implement the method described under the
  coverage table.
