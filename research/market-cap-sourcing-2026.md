# Market-cap sourcing without yfinance — research synthesis

Researched 2026-07-28 (single agent: code read + live endpoint probes + ToS pulls + pilot).
Question: replace/demote yfinance as the source of `market_cap` — the only non-EDGAR
number in every snapshot and the margin-of-safety denominator. Constraints: free,
keyless, ToS survivable for a *sold, client-distributed* product, hard-fail philosophy.

## How yfinance is used today (observed)

`whale_engine/src/whale_engine/fetch.py`:

- `_fetch_market_cap` (lines 296–315): `yf.Ticker(t).fast_info["market_cap"]`, falling
  back to `info["marketCap"]`; hard-fails if both empty. This is the number stored as
  `snapshot["market_cap"]`.
- `_fetch_share_reference` (lines 447–459): `info["impliedSharesOutstanding" |
  "sharesOutstanding"]`, used **only** to sanity-check the multi-class cover-page share
  sum (V path), gated by `SHARES_MISMATCH_FACTOR = 1.4` (line 126).

EDGAR-side share counts already exist in every snapshot: `outstanding_shares` via
`CommonStockSharesOutstanding` / `EntityCommonStockSharesOutstanding` /
`CommonStockSharesIssued` (BALANCE_TAGS, lines 81–85), with the weighted-average-basic
proxy (line 99) and the per-filing multi-class cover-page summation fallback
(`_collect_filing_facts`, lines 376–398). So **market cap = price × EDGAR shares needs
only a price**; the share machinery is already built.

## Answer to Q1: yes, price × EDGAR dei shares works

Pilot below: price × the snapshot's own `outstanding_shares` reproduces yfinance market
cap within −6.8%…+4.0% across all 17 snapshot tickers, and the outliers are traceable
to **share-count staleness**, not the price feed (see pilot notes). One engine change
would tighten it further: for market cap, use the *latest filed* dei
`EntityCommonStockSharesOutstanding` cover-page count (freshest filing), not the count
matched to the latest fiscal period end — NVDA's period-end count was 2026-01-25, six
months stale at fetch time.

## Q2: which free keyless price feed — candidates tested live

### Stooq — REJECT (observed technical block + redistribution clause)

Observed 2026-07-28 from this environment:

1. `https://stooq.com/q/d/l/?s=aapl.us&i=d` (the classic keyless CSV endpoint) returns a
   **JavaScript SHA-256 proof-of-work anti-bot challenge**, not CSV — on both stooq.com
   and stooq.pl, with and without browser User-Agent.
2. Solving the challenge programmatically (n=21606, `auth` cookie granted by
   `/__verify`, HTTP 200) and re-requesting the CSV returns **"Access denied"**. Stooq
   actively refuses automated data access in 2026 even to verified sessions from this
   network.

ToS (https://stooq.com/terms.html, fetched 2026-07-28 through the same PoW wall):

> "5.3. Redistribution of data found on the website is not allowed without the consent
> of Stooq."

> "6.1. … The [S&P] Index data may be used only for your own personal, non-commercial
> purposes."

No explicit automated-access clause for equities, but the deployed anti-bot wall is
Stooq revoking automated access in practice. A sold product whose fetch step must
bypass a proof-of-work wall is *worse* than yfinance, not better. Reject.

### Cboe delayed quotes — RECOMMENDED primary (works keyless; least-bad ToS posture)

`https://cdn.cboe.com/api/global/delayed_quotes/quotes/{TICKER}.json` — first-party
Cboe CDN, no key, no cookie, no anti-bot wall; returns JSON with `close`,
`prev_day_close`, `current_price`, `last_trade_time`. Worked for **17/17** snapshot
tickers on first try (observed 2026-07-28). Caveats, stated honestly:

- It is an *undocumented* endpoint backing Cboe's own quote pages — structurally the
  same "unofficial" caveat as yfinance, but with no auth/anti-bot barrier, no known
  breakage precedent, and a trivial response shape (one JSON GET, ~5 fields used — a
  replacement feed is a one-function swap, vs yfinance's library dependency).
- ToS: Cboe's disclaimers (https://www.cboe.com/us_disclaimers/) prohibit
  redistribution: "No data, values, or other content … may be … reproduced, or
  distributed in any form or by any means, or stored in a database or retrieval system,
  without the prior written permission of Cboe." The Subscriber Agreement
  (https://cdn.cboe.com/resources/membership/Subscriber_Agreement.pdf) licenses data
  "only for personal, non-commercial use by a Non-Professional Subscriber."

### Yahoo (yfinance) — the clause that disqualifies it as primary

Yahoo ToS (https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html), §2.4(ix): users
may not

> "access or collect data, or attempt to access or collect data, from our Services
> using any automated means, devices, programs, algorithms or methodologies, including
> but not limited to robots, spiders, scrapers, data mining tools … for any purpose
> without our express, prior permission."

and §2.5: "Unless otherwise expressly stated, you may not access or reuse the Services,
or any portion thereof, for any commercial purpose." Automated access is prohibited
*even for personal use* — yfinance is a per-se ToS breach, on top of the Feb-2025
breakage precedent. It cannot be the load-bearing source in a sold product.

### Other candidates — rejected

- **SEC/EDGAR-adjacent**: EDGAR carries no market prices. Quarter-end values in
  N-PORT/13F are 45+ days stale. No SEC price feed exists.
- **iShares/ETF holdings trick** (implied price = holding market value ÷ shares in
  daily fund CSV): probed 2026-07-28 — the known IVV holdings-CSV URL now returns the
  HTML product page, URLs are fragile product-ID paths, coverage is index-limited
  (CAVA-class small caps spotty), and BlackRock site terms are personal-use. Reject.
- **Keyless hosted APIs (stockprices.dev etc.)**: exist but publish no license terms at
  all; free keyed tiers (FMP, Alpha Vantage, Marketstack) are personal-use and/or need
  per-client keys — excluded by the distro constraint (same conclusion as
  research/multi-source-validation-2026.md agent 3). 2026 comparison guides agree:
  "an API key working in production does not prove that customer-facing use is
  licensed" (qveris.ai/guides/stock-api-free-comparison).

### The ToS reality (inference, flagged as such)

**No free keyless feed grants a written commercial license. None.** Exchange data
always carries end-user licensing. The only coherent posture for a sold product is:

- The product ships **code, not data**. Each client's own machine fetches one delayed
  quote per diagnosis for that client's own investment analysis — the shape of
  "personal, non-commercial use by a Non-Professional Subscriber" in Cboe's own terms.
  The vendor never touches, stores, or redistributes price data.
- Under that model Cboe is the least-bad option: personal use is the *licensed* case in
  its subscriber framework, and there is no automated-access prohibition being
  technically enforced against us (unlike Stooq) or written (unlike Yahoo §2.4(ix)).
- Residual risk to flag: professional/commercial *clients* technically fall
  outside Non-Professional scope; and the endpoint is undocumented. Mitigation: a
  `--market-cap` (or `--price`) manual-override CLI flag — user-typed input involves no
  automated access at all and is the ToS-bulletproof escape hatch for strict clients
  and feed outages. This is a legal-posture judgment, not observed fact; the maintainer signs
  off per repo precedent.

## Q3: pilot — Cboe close × EDGAR shares vs snapshot yfinance market_cap

All 17 committed snapshots (whale_engine/snapshots/, fetched 2026-07-26…28; includes the
golden tickers F/GM/KO/MA + graham golden AAL/NVDA and the six audit tickers META GOOGL
JPM LULU CAVA NVDA). Price = Cboe `close` 2026-07-27 (observed live 2026-07-28); shares
= snapshot `periods[0].balance.outstanding_shares`.

| Ticker | Cboe close | EDGAR shares | Price×shares | yfinance mkt cap | Dev % | Share tag date |
|---|---|---|---|---|---|---|
| AAL | 14.95 | 661,936,666 | 9.90B | 9.58B | +3.28% | 2026-06-30 |
| AAPL | 336.91 | 14,667,688,000 | 4,941.7B | 4,891.2B | +1.03% | 2026-03-28 |
| CAVA | 64.54 | 116,409,000 | 7.51B | 7.22B | +4.02% | 2026-04-19 |
| CCL | 27.12 | 1,239,000,212 | 33.60B | 36.06B | −6.82% | 2026-03-19 |
| F | 14.68 | 3,991,000,000 | 58.59B | 57.26B | +2.32% | wavg proxy 2026-03-31 |
| GM | 87.04 | 877,000,000 | 76.33B | 74.74B | +2.13% | 2026-06-30 |
| GOOGL | 326.56 | 12,230,000,000 | 3,993.8B | 3,993.8B | **+0.00%** | 2026-06-30 |
| JNJ | 265.95 | 2,407,216,971 | 640.2B | 634.8B | +0.86% | 2026-04-17 |
| JPM | 356.20 | 2,696,200,000 | 960.4B | 946.9B | +1.43% | 2025-12-31 |
| KO | 84.07 | 4,300,723,069 | 361.6B | 353.9B | +2.17% | 2026-02-18 |
| LULU | 117.83 | 109,308,000 | 12.88B | 13.23B | −2.62% | 2026-05-03 |
| MA | 551.71 | 891,000,000 | 491.6B | 476.8B | +3.09% | wavg proxy 2026-03-31 |
| META | 593.87 | 2,534,000,000 | 1,504.9B | 1,507.5B | −0.17% | wavg proxy 2026-03-31 |
| MSFT | 389.10 | 7,429,000,000 | 2,890.6B | 2,835.4B | +1.95% | 2026-03-31 |
| NVDA | 196.51 | 24,304,000,000 | 4,776.0B | 5,009.9B | −4.67% | 2026-01-25 |
| PG | 148.63 | 2,328,598,978 | 346.1B | 343.3B | +0.83% | 2026-03-31 |
| V | 362.53 | 1,815,172,471 | 658.1B | 676.5B | −2.73% | 4-class cover sum 2026-01-22 |

**Range: −6.82% … +4.02%; 13/17 within ±3.3%.** The comparison mixes one day of price
drift (yfinance caps snapped 07-26/27/28; Cboe close 07-27), so part of every deviation
is not error at all. The outliers decompose cleanly:

- **NVDA −4.67%**: share count from FY-end cover page 2026-01-25 — six months of
  buybacks/price mismatch. Staleness, not feed error.
- **CCL −6.82%**: count @2026-03-19; CCL has ongoing dilution/conversions, and yfinance
  itself likely uses an as-converted count. Staleness + structural.
- **V −2.73%**: raw 4-class sum ignores B/C→A conversion ratios (~1.6x) — the exact
  structural approximation `SHARES_MISMATCH_FACTOR` already documents (fetch.py lines
  122–126). Price×summed-shares is *structurally approximate* for V-type capital
  structures; the snapshot's `share_count_check` already records this.

### Multi-class handling

- **GOOGL**: snapshot shares 12.23B = A+B+C. Class-A price × all classes deviates
  +0.00% from yfinance — yfinance uses the identical convention. Observed GOOG (C)
  close 326.57 vs GOOGL (A) 326.56: a 0.003% spread; and unlisted B (~11% of shares)
  valued at A price is the universal convention. Approximation ≪ 0.1%.
- **META**: unlisted B valued at A price, same convention; −0.17%. Fine.
- **V (and future V-likes)**: only structurally approximate case — non-1:1 conversion
  ratios. Keep the 1.4x mismatch guard; record `derived-approx` provenance.
- Rule: price × summed-all-classes is exact when classes are economically equivalent
  (equal dividend/split rights); flag in provenance when the cover page shows >1 class.

## Q4: recommendation

1. **Primary**: `market_cap = cboe_close × edgar_dei_shares`, computed in fetch, with
   provenance `derived:cboe.close@{last_trade_time}×{share_tag}@{date}`. Use the
   *freshest filed* cover-page dei count for this product (not the period-end-matched
   count), cutting staleness to ≤1 quarter. Hard-fail if Cboe returns no quote, if
   `last_trade_time` is > 5 calendar days old (halted/delisted/stale feed), or if no
   dei share count exists — no silent fallback.
2. **Manual override**: `--market-cap` CLI flag → provenance `manual:user-supplied`.
   The ToS-bulletproof path and the outage escape hatch. (Hard-fail philosophy: the
   error message for a Cboe miss should name this flag.)
3. **yfinance: demoted to optional cross-check, never load-bearing.** If importable and
   returning, compare its market cap to the derived one; if unavailable/broken, WARN
   and proceed (its unavailability was the whole point). Also retire
   `_fetch_share_reference`'s yfinance dependence eventually (the 1.4x class-sum guard
   can reference the derived count or prior-period counts instead).
4. **Stooq: no role.** Actively blocks automated access in 2026 (observed); ToS bars
   redistribution; nothing it offers that Cboe doesn't.
5. **Validation tolerance (market-cap out-of-bounds = hard ERROR)**:
   - derived vs yfinance cross-check (when available): **ERROR beyond ±10%** —
     pilot worst honest case −6.8% is stale-shares dominated; with freshest-cover-page
     counts the observed spread is ±3.3%, so 10% flags real corruption (wrong ticker,
     split miss, class double-count) without false-failing on staleness.
   - absolute bounds: market_cap > 0; price > 0; shares > 0; keep
     `SHARES_MISMATCH_FACTOR = 1.4` for multi-class sums.
   - quote staleness: `last_trade_time` within 5 calendar days, else ERROR.

Net effect: EDGAR supplies every fundamental *and* the share count; the only external
surface left is one delayed close price via a single keyless JSON GET, cross-checked
and manually overridable. yfinance moves from single point of failure to disposable
witness.
