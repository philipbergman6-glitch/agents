# MCP Servers for Financial Data — Synthesis for the Buffett Scoring Engine

Baseline stack to beat/complement: **SEC EDGAR via edgartools (fundamentals, source-of-truth) + yfinance (prices, market cap)**. Required per ticker: 10 TTM periods of fundamentals (ROE, ROIC, D/E, margins, current ratio or raw line items) + market cap as-of-date. Marginal value of any MCP here is judged against that.

---

## 1. Ranked Shortlist (top 7)

**1. EdgarTools built-in MCP server (dgunning/edgartools)** — *Best fit.* This is the MCP the library you already chose ships in-package (`uvx edgartools-mcp`), so it exposes your exact decided backend to a Claude agent with zero new vendor, zero cost, MIT license, no API key. Full XBRL statements + Company Facts time-series back to 1994 comfortably covers 10 TTM periods; filing URLs returned for verification; unique live-filing monitor tool. Adds *convenience/agent-ergonomics*, not new data. Cost: free. Maturity risk: low for the library (~2.5k stars, ~4k commits, 2.3M downloads, last push 2026-07-19, Anthropic OSS program), but MCP-subcomponent standalone metrics are UNCONFIRMED. Gap: no native market cap (shares outstanding present; price must come from yfinance). https://github.com/dgunning/edgartools · https://www.edgartools.io/edgartools-mcp-for-sec-filings/

**2. sec-edgar-mcp (stefanoamorelli)** — Community wrapper over the *same* edgartools backend, so identical data provenance; head-to-head candidate vs #1. XBRL-parsed statements with "exact numeric precision," every response includes SEC filing URLs, handles SEC rate limits, ships stdio + streamable HTTP + Docker + PyPI. Cost: free, no key. Maturity: medium-high (~335 stars, 93 forks, versioned v1.0.6 Sep 2025 + Zenodo DOI, last push 2026-07-24). Key caveat: **AGPL-3.0 copyleft** — matters only if you redistribute a modified server. No market cap/valuation. Marginal value over #1 is near-zero (choose on license + tool ergonomics). https://github.com/stefanoamorelli/sec-edgar-mcp · https://pypi.org/project/sec-edgar-mcp/

**3. yahoo-finance-mcp (Alex2Yang97)** — Wraps the *same yfinance source you already assigned to prices/market cap*, giving an agent convenient market-cap-as-of-date and price lookups. Adds agent convenience, not new data, and inherits the same fragility (Yahoo undocumented rate limits / 429 blocking, ToS gray area). Cost: free, MIT, no key. Maturity: moderate (329 stars, 148 forks, last push 2026-03-23). Do NOT use as fundamentals source — Yahoo quarterly financials typically expose only ~4–8 periods, not 10 TTM. https://github.com/Alex2Yang97/yahoo-finance-mcp

**4. OpenBB MCP Server (openbb_platform mcp_server)** — *Best future convenience layer.* One MCP that can front both your chosen backends (SEC EDGAR + yfinance) via free paths AND optional premium providers (FMP, Polygon, Intrinio) behind a single interface with dynamic tool discovery to limit token bloat. You supply provider keys; SEC + yfinance routes are free. Cost: free/OSS (AGPLv3 / repo NOASSERTION). Maturity: parent repo huge and extremely active (70,962 stars, last push 2026-07-24) but MCP-extension standalone maturity is UNCONFIRMED. Heavier install than single-purpose servers; copyleft. https://github.com/OpenBB-finance/OpenBB

**5. Financial Datasets MCP (financial-datasets/mcp-server)** — *Best schema-match to the reference agent.* This is the native data layer of the ai-hedge-fund project your reference Buffett agent derives from, so pre-normalized statement objects map cleanly to Buffett-style scoring and reduce XBRL parsing. Income/balance/cash-flow + prices + news; "up to 30 years" history claimed; ratios NOT pre-computed (you derive — matches deterministic design); market cap via price×shares. Cost: free tier 100 req/day; paid from ~$49/mo; needs FINANCIAL_DATASETS_API_KEY. Maturity: most-starred finance MCP here (~2.2k stars, MIT, official) — BUT one finding cites last push **2025-06-05 (>1yr stale)** while another calls it "actively maintained"; conflict UNRESOLVED. Value = complementary cross-check, not source-of-truth (opaque normalization layer). https://github.com/financial-datasets/mcp-server · https://docs.financialdatasets.ai/mcp-server

**6. Financial Modeling Prep MCP (official endpoint + community imbenrabi)** — *Best fundamentals depth incl. pre-computed ratios.* FMP natively pre-computes the exact Buffett ratios (ROE, ROIC, D/E, margins, current ratio) + market cap + enterprise value, so it removes derive-from-line-items work; 30+yr statement history commonly cited. Community imbenrabi server is the most feature-rich (250+ tools, 24 categories, dynamic tool loading), Apache-2.0, actively maintained (141 stars, last push 2026-07-02, npm/Docker, Node 25.3.0+ for v2.6.0+). Cost: FMP key required; free tier ~250 req/day, US-only, ~5yr history; full history/ratios generally need paid (~$22–$99/mo, UNCONFIRMED). Trade-off: FMP-standardized, not SEC-authoritative + known restatement/quality quirks → use as convenience/cross-check, not source of truth. https://github.com/imbenrabi/Financial-Modeling-Prep-MCP-Server · https://site.financialmodelingprep.com/developer/docs/mcp-server

**7. Alpha Vantage MCP (official, alphavantage/alpha_vantage_mcp)** — The 2026 listicle "default" (ranked #1 across 4+ roundups — treat promotional). Vendor-official, 100+ tools, fundamentals normalized to SEC GAAP/IFRS taxonomies, MIT, actively maintained (~187 stars, last push 2026-07-22), broad client support. **Poor fit for THIS engine**, listed for completeness of strong options: (a) fundamentals history thin (~5yr annual / ~20 quarterly), no guarantee for deterministic 10-TTM; (b) no native TTM (compute from 4 quarters); (c) COMPANY_OVERVIEW market cap is CURRENT-only — cannot satisfy market-cap-as-of-date; (d) free tier **25 req/day** covers only ~6 tickers/day; premium from $49.99/mo. https://github.com/alphavantage/alpha_vantage_mcp · hosted https://mcp.alphavantage.co

---

## 2. Full Inventory

| Name | Provider | Official? | Data (fit for Buffett fundamentals) | Cost | Maturity | Link |
|---|---|---|---|---|---|---|
| EdgarTools built-in MCP | SEC EDGAR (edgartools) | No (first-party lib, not SEC) | Full XBRL statements, Company Facts time-series to 1994, 13 tools, live feed; ratios/market cap not native | Free, MIT, no key | Lib ~2.5k★, 2026-07-19; MCP metrics UNCONFIRMED | https://github.com/dgunning/edgartools |
| sec-edgar-mcp (stefanoamorelli) | SEC EDGAR (edgartools) | No | XBRL statements w/ exact precision + filing URLs, insider; no market cap | Free, **AGPL-3.0**, no key | ~335★, v1.0.6 + DOI, 2026-07-24 | https://github.com/stefanoamorelli/sec-edgar-mcp |
| yahoo-finance-mcp (Alex2Yang97) | Yahoo (yfinance) | No | Prices, market cap, statements (~4–5 periods only), holders, news | Free, MIT | 329★, 148 forks, 2026-03-23 | https://github.com/Alex2Yang97/yahoo-finance-mcp |
| Yahoo MCPs (hachecito, narumiruna, everdeep, peidaqi, danishashko, dino65) | Yahoo (yfinance) | No | Same as above; ~30 tools some; shallow fundamentals; 429/blocking risk | Free | Varies; yfinance fragile | https://github.com/hachecito/yfinance-market-mcp · https://github.com/narumiruna/yfinance-mcp |
| OpenBB MCP | Aggregator (SEC, yfinance, FMP, Polygon, Intrinio…) | Yes (first-party ext) | Everything OpenBB exposes; depth = provider key; dynamic tool discovery | Free/OSS AGPLv3; data = provider cost | Parent 70,962★, 2026-07-24; MCP UNCONFIRMED | https://github.com/OpenBB-finance/OpenBB |
| Financial Datasets MCP | financialdatasets.ai (SEC-sourced) | Yes | Normalized income/balance/cash-flow, prices, 30yr claim; ratios not exposed; mkt cap via price×shares | Free 100/day; paid ~$49/mo; key | ~2.2k★ MIT; last push conflict (2025-06-05 vs "active") | https://github.com/financial-datasets/mcp-server |
| FMP MCP (imbenrabi + official) | Financial Modeling Prep | Community + vendor official | 250+ tools; statements + **pre-computed ROE/ROIC/D-E/margins/current ratio + market cap**; 30+yr | Key req; free ~250/day US-only ~5yr; paid ~$22–99/mo (UNCONF) | 141★ Apache-2.0, 2026-07-02 | https://github.com/imbenrabi/Financial-Modeling-Prep-MCP-Server |
| Alpha Vantage MCP (official) | Alpha Vantage | Yes | Statements (GAAP/IFRS-normalized, ~5yr/~20q), overview w/ current-only mkt cap, TA, macro; no native TTM | Free 25/day, 5/min; premium $49.99/mo | ~187★ MIT, 2026-07-22 | https://github.com/alphavantage/alpha_vantage_mcp · https://mcp.alphavantage.co |
| calvernaz/alphavantage | Alpha Vantage | No (community; "official" badge misleading) | AV surface incl. fundamentals; OAuth 2.1, Prometheus, Lambda | AV free tier (25/day) | ~74★ Apache-2.0; last commit UNCONF | https://github.com/calvernaz/alphavantage |
| matteoantoci/mcp-alphavantage | Alpha Vantage | No | Modular incl. dedicated fundamentals category | AV free tier | ~3★ GPL-3.0; UNCONF | https://github.com/matteoantoci/mcp-alphavantage |
| berlinbra/alpha-vantage-mcp | Alpha Vantage | No | 12 tools: quotes, options, ETF, earnings — **no income/balance/cash-flow** | AV free tier | ~103★ MIT, active | https://github.com/berlinbra/alpha-vantage-mcp |
| Financial Modeling Prep (roundup listing) | FMP | No (listicle) | Deep fundamentals + SEC filings, 250+ tools, ratios | Key; free tier UNCONF | Top pick in roundups; no indep test | https://medium.com/predict/top-5-mcp-servers-for-financial-data-in-2026-5bf45c2c559d |
| EODHD MCP (official) | EODHD | Yes | 72–75 tools; bundled get_fundamentals (statements+valuation+mkt cap); global 70+ exch | Free plan; depth gated; v1 key / v2 OAuth | Med-high; major update 2026-03-31 | https://github.com/Enlavan/EODHD_MCP_server · https://eodhd.com/financial-apis/mcp-server-for-financial-data-by-eodhd |
| Intrinio native MCP | Intrinio | Yes | Standardized + as-reported fundamentals, prices, estimates; tool list/history UNCONF | Paid; self-serve plans from 2026-06; prices UNCONF | New MCP (2026-06 relaunch); early/thin | https://intrinio.com/blog/a-new-intrinio-for-the-ai-era |
| Polygon.io / Massive MCP (official) | Polygon.io / Massive | Yes | Prices/aggregates strong; stock financials (SEC-derived) secondary; mkt cap via ticker details | Free ~5/min EOD; paid ~$29/mo+ per asset class | 371★ MIT, 2026-06-11; **polygon→massive rebrand** | https://github.com/polygon-io/mcp_polygon · https://github.com/massive-com/mcp_massive |
| Nasdaq Data Link MCP (stefanoamorelli) | Nasdaq Data Link / Quandl | No | Macro/alt-data; equity fundamentals only via paid Sharadar SF1 (10+yr if subscribed) | Free MCP; datasets paid; key | 61★ MIT, 2025-10-04 (stale) | https://github.com/stefanoamorelli/nasdaq-data-link-mcp |
| Finnhub MCPs (cfdude, SalZaki C#, NimbleBrainInc, ach968, catherinedparnell) | Finnhub | No (all community) | Quotes, profiles (mkt cap), basic metrics; **full statements/As-Reported paywalled** | Free 60/min; Premium $11.99–99.99/mo | cfdude 10★ 2026-03-17; SalZaki ~4wk | https://github.com/cfdude/mcp-finnhub · https://github.com/SalZaki/finnhub-mcp |
| Tiingo MCP (wshobson; alt matteoantoci/major7apps) | Tiingo | No | 30+yr prices; fundamentals ~5yr free/15+yr premium — **now paid add-on in 2026** | Free ~250/day EOD; Power ~$30/mo; key | Community, ~2026-04-13, MIT | https://github.com/wshobson/tiingo-mcp |
| Twelve Data MCP (official) | Twelve Data | Yes | OHLCV, quotes, metadata, TA; "starter" fundamentals (paid); mkt cap via statistics | Free 800 credits/day, 8/min; Grow ~$29/mo | ~72★ MIT, ~2026-06-18; early-stage | https://github.com/twelvedata/mcp · https://mcp.twelvedata.com/mcp |
| AlphaSense MCP (reference) | AlphaSense (research intel) | Yes | ONE GenSearch tool → cited NL research answers; NOT structured numeric feeds | Enterprise; no public free tier | npm v1.1.2, ~1yr stale; reference-only, not hosted | https://developer.alpha-sense.com/agent-api/mcp-server |
| Shibui Finance MCP | Shibui (pre-loaded DB incl. EDGAR) | Yes (vendor claim) | 64yr US: 31M prices, quarterly+yearly statements, valuation metrics, 6.4M EDGAR records; "no rate limits" | No keys/rate limits claimed; tiers undisclosed | Vendor self-published; **no independent verification** | https://shibui.finance/guide-best-mcp-server-stock-data |
| MarketXLS MCP | MarketXLS | Yes | 1,100+ functions: statements, ratios, TA, options Greeks; US-only, no crypto | Paid $29.99/mo+ | Vendor self-ranked #1 (biased) | https://marketxls.com/blog/best-financial-data-mcp-servers-ai-market-data |
| Quiver Quantitative MCP | Quiver Quant | Yes | Alt-data: congress/hedge fund/insider/lobbying; **no financial statements** | UNCONF | Vendor self-published | https://www.quiverquant.com/news/Best+MCP+Servers+for+Stock+Data+in+2026 |
| sec-api.io (no MCP) / edgar.tools | sec-api.io / edgar.tools | No | sec-api.io = REST only, build-your-own MCP; edgar.tools = commercial SEC MCP | sec-api.io free 100 calls **lifetime**, $49–199/mo; edgar.tools $0–79/mo | sec-api client 2026-04-13 (no MCP); edgar.tools active | https://www.edgar.tools/ · sec-api.io |
| Databento MCP (Nice-Wolf-Studio, deepentropy, NimbleMarkets/dbn-go) | Databento | No (community) | Tick/microstructure/futures; **no equities fundamentals, no market cap (both "in development")** | $125 credit then usage; subs ~$179–4,000/mo (UNCONF) | Community; official libs only | https://github.com/Nice-Wolf-Studio/databento-mcp-server · https://github.com/NimbleMarkets/dbn-go |
| StockMCP (leogue) | Yahoo (FastAPI wrap) | No | Quotes, history, basic fundamentals; free hosted endpoint | Free, no key, no license | 4★, 2025-08-27; personal project | https://github.com/leogue/StockMCP |
| Stooq MCP (hoqqun) | stooq.com (scrape) | No | Prices only, multi-market; **no fundamentals, no market cap** | Free; unofficial/unstable | Single-author Rust, MIT | https://github.com/hoqqun/stooq-mcp |
| finData MCP (zlinzzzz) | Tushare/Wind/DataYes | No | China A-share fundamentals | Free MCP; providers paid | 57★ Apache-2.0, 2025-05-09 (stale) | https://github.com/zlinzzzz/finData-mcp-server |
| mcp-baostock-server (HuggingAGI) | Baostock | No | China A-share prices+fundamentals | Free | 114★ no license, 2026-03-22 | https://github.com/HuggingAGI/mcp-baostock-server |
| Alpaca MCP (alpacahq et al.) | Alpaca Markets | No | Trading/brokerage + bars/quotes; **not a fundamentals provider** | Alpaca tiers | N/A (disambiguation only) | https://github.com/alpacahq/alpaca-mcp-server |

---

## 3. Skip These

- **berlinbra/alpha-vantage-mcp** — No income/balance/cash-flow statements; prices/options/earnings only.
- **matteoantoci/mcp-alphavantage** — Immature (~3★, GPL-3.0); use official AV if you want AV.
- **AlphaSense MCP** — Returns NL cited research answers, not machine-parseable numeric line items; enterprise-gated; reference impl, not hosted.
- **Alpaca MCP** — Broker/trading, not a fundamentals family member (disambiguation only).
- **Databento MCP** — No equities fundamentals AND no market cap (both "in development"); microstructure overkill.
- **Quiver Quantitative MCP** — Alt-data (congress/insider) only; no financial statements.
- **Polygon roundup / MarketXLS-cited Polygon** — "Reference data only, no financial statements"; fundamentals SEC-derived so no edge over EDGAR.
- **Stooq MCP** — Prices only, no fundamentals/market cap; unofficial scrape, blocking risk.
- **StockMCP (leogue)** — Personal project (4★, no license); throwaway experiments only.
- **finData / mcp-baostock** — China A-share focus; out of scope for US Buffett engine.
- **sec-api.io** — No MCP exists (build-your-own); free tier is 100 calls *lifetime*; no advantage over free EDGAR.
- **Finnhub MCPs** — Full statements/As-Reported paywalled; free fundamentals too shallow for 10 TTM line items (use only as price/mkt-cap channel).
- **Tiingo / Twelve Data / Nasdaq Data Link** — Fundamentals paid/"starter"/gated (Tiingo now add-on, TwelveData "starter" paid, Nasdaq needs paid Sharadar); price/cross-check use only.
- **Intrinio / EODHD / MarketXLS** — Paid, vendor-normalized; overkill vs free EDGAR unless you add international (EODHD) or need institutional normalization (Intrinio).

---

## 4. Open Questions / Unconfirmed Claims

1. **Financial Datasets MCP maintenance status** — findings conflict: last push **2025-06-05 (>1yr stale)** vs "actively maintained." Verify repo commit history before depending; API itself may still be live. https://github.com/financial-datasets/mcp-server
2. **EdgarTools & OpenBB MCP standalone maturity** — all star/commit metrics are library/repo-wide, NOT MCP-subcomponent specific. Standalone MCP adoption UNCONFIRMED.
3. **Alpha Vantage fundamentals depth** — exact per-statement report count (~5 annual / ~20 quarterly) is CONFIRMED in structure but exact count UNCONFIRMED from official docs; no `years` param (client-side slice). Critical: this thin history is the reason AV can't guarantee the 10-TTM requirement — verify before relying.
4. **Market-cap-as-of-date coverage** — NO EDGAR-based server provides historical market cap (EDGAR has shares outstanding only). Must compute shares × historical price via yfinance. Confirm shares-outstanding timing aligns with price date.
5. **TTM assembly** — None of the EDGAR/edgartools servers document native TTM aggregation; you compute TTM from 4 quarters. FMP/Financial Datasets expose TTM natively but as vendor-normalized numbers.
6. **Pricing UNCONFIRMED** — FMP ($22–99/mo), Financial Datasets ($49/mo), Polygon/Massive, Intrinio, Databento ($179–4,000/mo third-party figures), Twelve Data. Verify at vendor pricing pages with "2026".
7. **Polygon → Massive rebrand** — cause and pricing impact UNCONFIRMED (billed per asset class post-rebrand). Investigate repo/org migration before adopting. https://github.com/massive-com/mcp_massive
8. **calvernaz "official" badge** — repo displays "Official Alpha Vantage MCP Server" badge but is a community repo (not the alphavantage org); treat badge skeptically. Also last-commit date UNCONFIRMED.
9. **Tiingo repo canonicity** — both wshobson/tiingo-mcp and major7apps/tiingo-mcp surfaced under the same PyPI name; which is canonical UNCONFIRMED.
10. **Shibui Finance** — all claims ("64yr data, no rate limits, no per-query cost") are vendor self-published with zero independent verification; the local-cache/DuckDB pattern it markets IS independently validated by HN thread 47768969, but coverage/reliability are not.
11. **Financial Datasets free-tier accuracy** — no accuracy complaints found either way (UNCONFIRMED); one finding lists free unlimited only for AAPL/NVDA/MSFT/GOOGL/TSLA + 100 req/day elsewhere. Spot-check normalized values vs EDGAR before trusting.
12. **EODHD / Intrinio per-statement history depth** — not precisely documented in sources (UNCONFIRMED).

**Design lesson (not a server):** Databento HN redesign (item 47768969) — naive "wrap the API" MCPs dump a firehose (one call = tens of thousands of tokens) into context. For 10 TTM × many tickers, prefer MCPs returning compact structured rows or local cache (Parquet + DuckDB / Shibui pre-loaded DB pattern) over raw-streaming servers. https://news.ycombinator.com/item?id=47768969

**Bottom line:** No MCP displaces edgartools+yfinance as source-of-truth. Highest-value adds are (a) the **edgartools/sec-edgar MCP** as an agent-ergonomic wrapper over your existing backend, (b) **OpenBB** as a future single-interface convenience layer fronting both your free backends, and (c) **FMP or Financial Datasets** as *complementary cross-check* channels (pre-computed ratios / clean statement schemas) — never as deterministic source of truth given their unauditable normalization.
