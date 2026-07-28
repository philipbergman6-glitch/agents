# Multi-source data validation & extension — research synthesis

Researched 2026-07-28 via three parallel research agents (web + GitHub). Question: beyond
EDGAR + yfinance, what data would most improve the whale engine's accuracy/credibility —
for us, for retail users, and for hedge-fund-style assessment of a ticker? Constraint:
free sources only, client-distributed package (no per-client API keys).

## Agent 1 — what data actually drives single-ticker assessment

Ranked by assessment value per unit of effort (academic + practitioner + Buffett primary sources):

1. **Audited fundamentals w/ ~10y history** — the only category with consistent
   return-predictive academic evidence (Piotroski F-score spreads ~10–18%/yr across
   markets) AND Buffett's stated starting point. Cheap, structured. *(We already do this.)*
2. **Price vs intrinsic value (entry valuation)** — near-zero marginal effort once
   fundamentals exist; starting valuation strongly predicts 10-yr returns. *(We already do this.)*
3. **Qualitative moat evidence** — highest ceiling (the professional differentiator) but
   highest cost and documented false-conviction risk. Best used narrowly: "is the
   historical ROIC durable?"
4. **13F/insider positioning** — good screen/confirmation, poor single-ticker thesis
   driver (45-day lag, no context). One cheap sub-signal worth having: **insider cluster
   purchases** (Form 4; +2.1%/mo abnormal returns in studies, strongest in small caps).

Retail benefits most from 1+2 (fully democratized, amplified by retail's structural
edges: horizon, no redemption pressure). Hedge funds' marginal edge is 3 (expert
networks/channel checks) — expensive, mostly intra-quarter timing, not replicable free.

## Agent 2 — how existing Buffett-style tools do it

- ai-hedge-fund (~50k stars): Buffett persona = numeric heuristics (moat = ROE
  consistency + margin stability) + LLM narration. **No news/13F/insider data in the
  persona.** Same shape as our engine, minus our determinism discipline.
- Validea/GuruFocus/Simply Wall St: all concede the qualitative step ("a business we
  understand") is unscreenable and delegate it to the user.
- Field-wide criticism pattern: heuristic tools lack qualitative grounding; LLM-text
  tools lack reliable numbers; silent data gaps treated as neutral signal (ai-hedge-fund
  issue #624) destroy trust.
- **The input that most improves credibility: primary-source filings — structured XBRL
  *and* narrative text (MD&A, competition sections) — with point-in-time discipline.**
  Second: revealed-preference cross-check (13F/13D + Form 4) — used by zero persona
  simulators today. Least trusted input: news/social sentiment (also off-persona for
  Buffett/Graham).

## Agent 3 — free cross-validation reality check

- **A second external fundamentals source is NOT worth it.** Every free source
  (FMP/Alpha Vantage/Finnhub/SimFin) re-derives from the same EDGAR filings — no
  statistical independence — and every hosted free tier is non-commercial and/or
  requires per-client API keys, which our distributed product can't ship.
- The errors that actually threaten us are **parsing-layer** errors: XBRL tag selection,
  custom/deprecated tags, duplicate facts from amended filings, YTD-vs-quarter math,
  fiscal alignment (LULU Jan-FY), dei shares outstanding (filing-date, multi-class
  blending), and **restatements filed via 8-K Item 4.02 that never amend the original
  10-K** (stale wrong facts persist in companyfacts forever).
- Best free validation stack (all keyless, public domain):
  1. **Internal consistency checks** on each snapshot: balance-sheet identity,
     sign/scale bounds, YoY jump detection (1000x = scale error), YTD reconciliation.
  2. **Second SEC-side extraction as cross-validator**: diff edgartools values against
     SEC's own bulk `companyfacts.zip` / Financial Statement Data Sets — catches parser
     bugs with zero new ToS exposure.
  3. **Restatement guard**: scan filing history for 8-K Item 4.02 (non-reliance) and
     flag affected fiscal years in the snapshot.
- **yfinance is the weakest link in the current stack** (unofficial scraping, Feb-2025
  breakage precedent, no commercial license). For a sold product: derive market cap as
  price × EDGAR dei shares; Stooq price as cross-check (personal-use ToS caveat —
  flag to owner); EDGAR-derived data is the only fully ToS-clean layer.
- Free extensions, all via EDGAR/edgartools (zero new deps, ToS-clean): 13F-HR
  holdings, Form 3/4/5 insiders, 8-K material news. Transcripts: no ToS-clean keyless
  source of record (defeatbeta-api exists but Yahoo-derived provenance); prepared
  remarks largely overlap MD&A/8-K anyway. GDELT only if large-scale news ever needed.

## Combined conclusion

1. **Don't add a second external fundamentals provider.** It adds ToS risk and no real
   independence. "Not all from one place" is better served by validating the parse
   (companyfacts.zip diff + internal invariants + restatement guard) than by a second
   scrape of the same filings.
2. **The real single-point-of-failure is yfinance**, not EDGAR. Fixing market-cap
   sourcing is higher-value than a fundamentals second source.
3. **To "truly act as the whales," the highest-credibility additions are more EDGAR,
   not new vendors:** filings narrative text grounding the moat/qualitative dimensions,
   Form 4 insider-cluster signal, and 13F revealed-preference cross-check (already the
   roadmap's 13F/panel item). News/sentiment: skip — least trusted, off-persona.
4. Benefit split: retail users gain most from hardened fundamentals + honest failure
   modes (no silent gaps); the hedge-fund-style edge comes from the filings-text
   qualitative layer — which happens to be the field-wide gap no persona tool fills.
