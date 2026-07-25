# 13F whale-holdings module — feasibility research

Resolves [#22](https://github.com/philipbergman6-glitch/agents/issues/22). All facts below verified directly against SEC EDGAR on 2026-07-25 (company search + `data.sec.gov/submissions` JSON + a live edgartools parse). No numbers estimated.

## Verdict

**Feasible as specified.** All 16 candidate funds have an active 13F-HR filer on EDGAR, current through Q1 2026 (period 2026-03-31, filed 2026-05-15). edgartools (5.43.0, already a dependency) parses 13F-HR filings into a holdings DataFrame with tickers resolved — same fetch→pinned-snapshot→offline-report model as fundamentals, zero new dependencies.

## Confirmed roster (CIK registry)

| Fund (owner's name) | EDGAR filer | CIK | Latest 13F-HR |
|---|---|---|---|
| Berkshire Hathaway | BERKSHIRE HATHAWAY INC | 1067983 | 2026-05-15 (Q1 2026) |
| Pershing Square | Pershing Square Capital Management, L.P. | 1336528 | 2026-05-15 (Q1 2026) |
| Greenlight | DME Capital Management, LP | 1489933 | 2026-05-15 (Q1 2026) |
| Icahn | ICAHN CARL C (individual) | 921669 | 2026-05-15 (Q1 2026) |
| Third Point | Third Point LLC | 1040273 | 2026-05-15 (Q1 2026) |
| Appaloosa | Appaloosa LP | 1656456 | 2026-05-15 (Q1 2026) |
| Fairholme | FAIRHOLME CAPITAL MANAGEMENT LLC | 1056831 | 2026-05-15 (Q1 2026) |
| Maverick | MAVERICK CAPITAL LTD | 934639 | 2026-05-15 (Q1 2026) |
| Viking | VIKING GLOBAL INVESTORS LP | 1103804 | 2026-05-15 (Q1 2026) |
| Lone Pine | LONE PINE CAPITAL LLC | 1061165 | 2026-05-15 (Q1 2026) |
| Tiger Global | TIGER GLOBAL MANAGEMENT LLC | 1167483 | 2026-05-15 (Q1 2026) |
| Fundsmith | Fundsmith LLP | 1569205 | 2026-05-15 (Q1 2026) |
| Lindsell Train | Lindsell Train Ltd | 1484150 | **2026-07-15 (Q2 2026)** — early filer |
| Giverny | Giverny Capital Inc. | 1641864 | 2026-05-15 (Q1 2026) |
| TCI | TCI Fund Management Ltd | 1647251 | 2026-05-15 (Q1 2026) |
| Leon Cooperman (Omega) | COOPERMAN LEON G (individual) | 898382 | 2026-05-15 (Q1 2026) |

### Entity resolution notes (non-obvious)

- **Greenlight → DME Capital Management, LP.** GREENLIGHT CAPITAL INC (CIK 1079114) stopped after Q4 2023 (filed 2024-02-14); DME's first 13F covers Q1 2024 (filed 2024-05-15) — clean succession, no overlap, and DME's business address (140 E 45th St, 24th Fl, NYC) is Greenlight's. Inference (strongly supported): rename/successor entity for Einhorn's book.
- **Omega Advisors Inc. (CIK 898202) stopped filing after Q4 2018** (family-office conversion). Cooperman files personally as COOPERMAN LEON G (CIK 898382), current through Q1 2026 — use that CIK.
- **Icahn:** five stale Icahn entities on EDGAR; the live filer is the individual CIK 921669.
- **Appaloosa:** APPALOOSA MANAGEMENT LP (1006438) stopped 2015; Appaloosa LP (1656456) is the live filer.
- **Giverny is ambiguous in the wild but not on EDGAR:** only Rochon's Giverny Capital Inc. (Montreal) actively files. Poppe's Giverny Capital Asset Management renamed to 11 Capital Partners LP (CIK 1801172, also active) — if the owner meant Poppe, swap/add that CIK.
- **Dual active filers to watch for double-counting:** PERSHING SQUARE INC. (2026053, new entity, files since 2025) alongside the LP; FUNDSMITH INVESTMENT SERVICES LTD. (1868537) alongside Fundsmith LLP. Roster tracks the flagship (LP / LLP); implementation should note the sibling CIKs, not sum them.
- UK-based Fundsmith and Lindsell Train **do** file 13F-HRs (verified above) — US-listed holdings only, as expected.

## edgartools 13F support (verified live)

```python
tf = Company(cik).get_filings(form="13F-HR")[0].obj()   # ThirteenF
tf.report_period    # '2026-03-31'
tf.infotable        # DataFrame
```

`infotable` columns: `Issuer, Class, Cusip, Value, PutCall, InvestmentDiscretion, OtherManager, SharesPrnAmount, Type, SoleVoting, SharedVoting, NonVoting, Ticker`. Verified on Giverny Q1 2026: 51 rows, tickers resolved (BRKB, GOOG, META, HEIA, SCHW…).

### Implementation gotchas surfaced

1. **Ticker normalization:** edgartools resolves CUSIP→ticker but in dot/dash-less form (`BRKB`, `HEIA` vs yfinance's `BRK-B`, `HEI-A`). Match on **CUSIP** where possible (snapshot the queried ticker's CUSIP at fetch time), or normalize by stripping `-`/`.` before comparing. Some CUSIPs may not resolve to a ticker at all — hard-fail rules should treat blank Ticker as "match by CUSIP only", not crash.
2. **Aggregation:** one issuer can span multiple rows (share classes, sub-managers, puts/calls). Aggregate `SharesPrnAmount` by CUSIP after **excluding rows with `PutCall` set** (options aren't share ownership; surface them separately or not at all).
3. **Amendments:** 13F-HR/A restatements exist (Berkshire files them regularly). Fetch should prefer the latest amendment for a period when one exists.
4. **Mixed periods across funds:** filers lag differently (Lindsell Train already has Q2 2026 while everyone else is on Q1). Don't force a common quarter — diff each fund's latest two filings and label the period per fund in the report.
5. **Value units:** since Q2 2022 the `Value` column is whole dollars (older filings were $ thousands) — irrelevant if only latest-two are fetched, but don't extend history naively.

## Recommended shape (proposal, for the implementation ticket)

- Roster as data: `whales_13f.json` (name → CIK + sibling-CIK notes) in the engine package — editable without code changes.
- `fetch-13f`: for each roster CIK, pull latest two 13F-HR (amendment-aware) → one snapshot file per CIK+period (whale-agnostic raw holdings, matching the snapshot philosophy).
- `holdings TICKER`: offline; resolves ticker→CUSIP from snapshots, aggregates per fund, diffs latest-two → `opened / added / trimmed / exited / unchanged` + position size; prints the 45-day-lag / long-only / US-listed caveats verbatim in every report.
