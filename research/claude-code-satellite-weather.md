# Connecting Claude Code to Free Satellite Imagery & Weather Data — Options Map

**Research date:** 2026-07-26 · **Scope:** every genuinely-free path from Claude Code (Bash/MCP) to satellite imagery and weather/forecast-model data.

**File placement note.** This repo (`agents/`) is a finance-agent repo — this research is unrelated to its domain. It already has a `research/` directory with three primary-source synthesis notes (`13f-whale-holdings.md`, `data-source-comparison.md`, `mcp-servers-financial-data.md`), so this follows that existing convention rather than creating a new one.

**Evidence tags used throughout:**
- **OBSERVED** — read directly from the cited official doc, or returned by a live call to the official endpoint on 2026-07-26.
- **INFERRED** — deduced from observed facts; reasoning stated.
- **UNCONFIRMED** — could not be verified in any primary source. **No rate limit, quota or price in this document is invented.** Where a number circulates on secondary sites but could not be confirmed, it is named as unconfirmed and not asserted.

---

## 0. Executive summary — the five paths worth taking

| # | Path | Why | Auth |
|---|---|---|---|
| **1** | **Open-Meteo over plain `curl`** (no MCP needed) | Keyless JSON, 20+ national models incl. ECMWF IFS/GFS/HRRR/ICON, forecast + historical + marine + air quality + flood + ensemble. Documented limits. Single biggest gotcha: **free tier is non-commercial only.** | none |
| **2** | **`api.weather.gov` over plain `curl`** (US) | Keyless, federal, GeoJSON, alerts/CAP. This is what the *official* MCP quickstart server wraps — you rarely need the wrapper. | User-Agent header only |
| **3** | **Anonymous S3 + `.idx` byte-range on NOAA/ECMWF open data** | Raw NWP + GOES/Himawari imagery, no account, no SDK. Verified live: 519 KB pulled from a 509 MB GFS file with `curl` alone (981× reduction). | none |
| **4** | **STAC search + COG read** (Earth Search / Planetary Computer / LandsatLook) | Anonymous Sentinel-2/Landsat/DEM discovery and pixel access; `pystac-client` + `odc-stac`, or pure `curl`+`jq`. | none (see Landsat trap) |
| **5** | **MCP servers — only where a key must be injected or real computation happens** | `isdaniel/mcp_weather_server` (Open-Meteo, Apache-2.0, active), `Wayfinder-Foundry/stac-mcp`, `JordanGunn/gdal-mcp`. For keyless REST, MCP adds ergonomics, not capability. | varies |

**The load-bearing conclusion:** for keyless REST APIs, an MCP server is *convenience*, not capability — Claude Code's Bash tool with `curl`/`jq`/`uv run` reaches every free source in this document. MCP earns its keep in exactly two cases: (a) credential injection for key-gated APIs, which WebFetch cannot do; (b) real local computation on pixels (COG reads, NDVI, reprojection) that no fetch tool can substitute for.

---

# PART I — SATELLITE IMAGERY

## 1. NASA GIBS / Worldview — best zero-auth imagery source

**What:** >1,000 pre-rendered global visualization layers (live capabilities count on 2026-07-26: **1,268 `<Layer>` blocks**). MODIS Terra/Aqua, VIIRS SNPP/NOAA-20/21 true colour, IMERG precipitation, GOES-East GeoColor with a rolling **PT10M** sub-daily window, vector layers as Mapbox Vector Tiles. OBSERVED — https://nasa-gibs.github.io/gibs-api-docs/available-visualizations/

**Endpoints** (OBSERVED — https://nasa-gibs.github.io/gibs-api-docs/access-basics/), all on `https://gibs.earthdata.nasa.gov`:
- WMTS REST: `/wmts/epsg{4326|3413|3031|3857}/best/{Layer}/default/{Time}/{TMS}/{z}/{y}/{x}.{ext}`
- WMS 1.1.1/1.3.0: `/wms/epsg{code}/best/wms.cgi?` · TWMS: `/twms/epsg{code}/best/twms.cgi?`
- GetCapabilities: `/wmts/epsg4326/best/1.0.0/WMTSCapabilities.xml`
- `best` swaps to `std` / `nrt` / `all`.

**Auth/cost:** **No Earthdata Login, no API key, free.** A grep of every page in the docs repo for `authenticat|token|api key|earthdata login|registration` returned zero matches (OBSERVED). Empirically: anonymous `curl` of a VIIRS tile → `HTTP 200, image/jpeg, 54,845 bytes`, `access-control-allow-origin: *` (OBSERVED). INFERRED that no auth is needed — no page states it affirmatively.

**Rate limits:** GIBS publishes **bulk-download *guidelines*, not enforced limits** (OBSERVED, verbatim, https://nasa-gibs.github.io/gibs-api-docs/map-library-usage/#bulk-downloading): *"A 'Bulk Download' is defined as the planned retrieval of more than 1,000,000 imagery tiles within a 24 hour period … coordinated at least 48 hours in advance … 1. Limit sustained download bandwidth to 50 Mbps … 2. Limit concurrent downloads to 500 threads."* Any hard per-IP cap or 429 behaviour: **UNCONFIRMED**.

**Latency — two official figures that disagree (OBSERVED):** gibs-api-docs says NRT *"within 3.5 hours"*, STD *"within 24 hours"*; the Earthdata developer portal (updated 2026-07-09) says *"available within 3-5 hours"*. INFERRED: plan for ~3–3.5 h NRT.

**Formats:** `image/jpeg`, `image/png`, `application/vnd.mapbox-vector-tile`; WMS additionally serves `image/tiff` (OBSERVED — NASA's own notebook requests `format='image/tiff'`).

**Claude Code path:** pure `curl` against a WMTS tile URL, or **GDAL** ≥1.9.1 TMS/WMTS minidrivers → `gdal_translate`/`gdalwarp`, or **OWSLib** 0.36.0 per NASA's own notebook. **No first-party download CLI exists** (OBSERVED — full listing of https://github.com/orgs/nasa-gibs/repos yields only `worldview`, `gibs-api-docs`, `gibs-web-examples`, `onearth`, `mrf`, `gibs-gdal`).

**Doc discrepancy worth knowing (OBSERVED):** the docs tile-matrix table lists `15.125m` and omits `16km`; `15.125m` does not appear in live capabilities. Trust GetCapabilities over the docs table.

### 1b. Worldview Snapshots — the underrated one

Renders any GIBS layer to a georeferenced image on demand. Verified live 2026-07-26 (OBSERVED):

```
https://wvs.earthdata.nasa.gov/api/v1/snapshot?REQUEST=GetSnapshot&LAYERS=…&CRS=EPSG:4326
  &TIME=2026-07-20&BBOX=-20,-20,20,20&FORMAT=image/jpeg&WIDTH=512&HEIGHT=512[&WORLDFILE=true]
```

200 confirmed for `image/jpeg`, `image/png`, `image/tiff`, `application/vnd.google-earth.kmz`, and `WORLDFILE=true` → `application/zip`. EPSG:3031 works; multi-layer compositing works; a layer *not* in the UI (`IMERG_Precipitation_Rate`) also returned 200 → INFERRED the API accepts arbitrary GIBS layer IDs.

- **Anonymous** — every probe succeeded with no EDL token (OBSERVED). This contradicts the catalog page's generic *"An Earthdata Login is required to download data"*, which appears to be a site-wide template string (INFERRED).
- **No published parameter reference** — `https://wvs.earthdata.nasa.gov/api/v1/docs` returns 404 (OBSERVED). De-facto public, formally undocumented.
- **Trap (OBSERVED):** errors return **HTTP 200** with an OGC `<ServiceExceptionReport>` body. `raise_for_status()` silently passes errors — parse the body.
- **Size:** 10000×10000 verified 200; 12000×12000 → `RequestTooLarge`. True cap in (10000, 12000] px/side, **UNCONFIRMED**. Latency 20–42 s for 2k–8k images (OBSERVED) — set generous timeouts.
- Sensors: MODIS Terra/Aqua, VIIRS SNPP/NOAA-20/21, **PACE OCI**; latency *"approximately three hours after a satellite observation"* via LANCE (OBSERVED, https://www.earthdata.nasa.gov/data/tools/worldview-snapshots).

## 2. NASA Earthdata — CMR search + Earthdata Login

**CMR Search API** — `https://cmr.earthdata.nasa.gov/search/` (OBSERVED, https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html). Formats: HTML, Atom, CSV, DIF-9/10, ECHO10, ISO, JSON, UMM-JSON, KML, Open Data, **STAC**, native.

- **Anonymous for public search** — live: `collections.json?short_name=MOD09GA` → HTTP 200 with no `Authorization` header, `cmr-hits: 1508497` (OBSERVED).
- **Auth only for restricted/private metadata and subscriptions** (OBSERVED, verbatim): *"For private collection, an EDL bearer token or a Launchpad token can be used."*
- **Documented limits (OBSERVED, verbatim):** default `page_size` 10, *"max is 2000"*; *"You can not page past the 1 millionth item"*; uncollected granule queries limited to *"paging up to the 10,000th item"*; *"hard limit of 180 seconds … internal query timeout of 170 seconds"*; scroll deprecated → `CMR-Search-After`, scroll requests *"will return HTTP 400 errors"*.
- **Rate limiting exists, thresholds deliberately unpublished (OBSERVED, verbatim):** *"CMR Search deploys a set of rate throttling rules … the request will be rejected and a 429 error status returned … along with a `retry-after` header value."* Numeric thresholds **UNCONFIRMED** — honour `Retry-After`, do not hard-code.

**Earthdata Login (EDL)** — free account, `POST /api/users/token` (OBSERVED, https://urs.earthdata.nasa.gov/documentation/for_users/user_token). Verbatim: **"User tokens are valid for a duration of 60 days. A user is allowed a maximum of two valid user tokens at any given time."** EDL API rate limits **UNCONFIRMED**.

**`earthaccess`** — *"a Python library to search for and download or stream NASA Earth science data with just a few lines of code"* (OBSERVED, https://earthaccess.readthedocs.io/). PyPI 0.18.0, MIT, **requires Python ≥3.12** (the quick-start page still says 3.8 — stale).

- **Premise correction (OBSERVED, live curl):** `github.com/nsidc/earthaccess` **301-redirects to `github.com/earthaccess-dev/earthaccess`**. It has moved out of the NSIDC org.
- **Agent-friendly auth:** env vars `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD` or `EARTHDATA_TOKEN` are tried first, then `.netrc`, then interactive input (OBSERVED). The env-var path is fully non-interactive — INFERRED, the correct one for a CLI agent.
- **Region caveat, critical (OBSERVED):** *"Accessing data directly in the cloud from the us-west-2 S3 region is free to the user"*; *"Data from NASA Earthdata's S3 buckets currently cannot be accessed from a different AWS region."* Use `granule.data_links(access="external")` (on-prem HTTPS) off-region.

Other first-party Python: `python-cmr` 0.13.0 (`nasa/python_cmr`), `harmony-py` 1.5.0 (`nasa/harmony-py`).

## 3. NOAA GOES-16/17/18/19 on AWS Open Data — best free geostationary archive

**Access (OBSERVED — https://registry.opendata.aws/noaa-goes/ + live probes):** buckets `noaa-goes16`, `noaa-goes17`, `noaa-goes18`, `noaa-goes19`, all **us-east-1**. **Truly anonymous, NOT requester-pays** — plain unauthenticated `curl https://noaa-goes19.s3.amazonaws.com/?list-type=2…` returned full XML listings with zero credentials.

**Licence (OBSERVED, verbatim):** *"NOAA data disseminated through NODD are open to the public and can be used as desired."* Attribution requested, not required.

**Which satellite is which in 2026 — get this right (OBSERVED):** **GOES-19 = GOES-East (75.2°W); GOES-18 = GOES-West** (https://www.nesdis.noaa.gov/our-satellites/currently-flying/geostationary-satellites). OSPO verbatim: *"On April 4, 2025 at 1510 UTC, the GOES-19 satellite will be declared the Operational GOES-East satellite."* **Data-continuity answer: 7 April 2025** — `noaa-goes16/ABI-L1b-RadF/` ends at `2025/097`. `noaa-goes17` ends `2023/010`.

**Structure:** `<Product>/YYYY/DDD/HH/`; real key `ABI-L1b-RadF/2026/206/12/OR_ABI-L1b-RadF-M6C01_G19_s20262061200209_e…_c….nc`. **Format NetCDF4** (SUVI also FITS). Products: ABI L1b `RadF`/`RadC`/`RadM`; ABI L2 `CMIP`, `MCMIP`, `ACHA`, `ACM`, `AOD`, `COD`, `CTP`, `DMW`…; plus `GLM-L2-LCFA`, `SUVI-L1b-*`, `EXIS-L1b-*`, `MAG-L1b-GEOF`, `SEIS-L1b-*`. GOES-18/19 only: `ABI-Flood-Day`, `ABI-Flood-Hourly` (OBSERVED, live listings).

**Resolution/cadence (OBSERVED, https://www.goes-r.gov/spacesegment/abi.html):** 16 bands; 0.5 km band 2, 1 km other VIS/NIR, 2 km >2 µm. Mode 6: full disk **10 min**, CONUS **5 min**, meso **60 s** (both) or **30 s** (one). Both operational satellites confirmed in Mode 6 (`cdn.star.nesdis.noaa.gov/GOES19/ABI/mode.txt` → `6`).

**Latency ≈ 25 s from file creation, ~10 min from scan start** — a key with creation stamp 12:09:55.8 had S3 `LastModified 2026-07-25T12:10:17Z`, consistent across 4 consecutive granules (OBSERVED). RadF C01 granules ~49–55 MB.

**Rate limits: UNCONFIRMED** — nothing on the registry page; noaa.gov NODD pages return 403 to automated fetches.

**Claude Code path:** `aws s3 ls --no-sign-request s3://noaa-goes19/` · `s3fs.S3FileSystem(anon=True)` · **`goes2go`** (github.com/blaylockbk/goes2go, MIT, 2025.10.0, Python ≥3.10, **supports GOES-19**). **Caveat (OBSERVED):** legacy `goes2go/NEW.py` still hardcodes only `noaa-goes16/17` and derives its product list from `fs.ls("noaa-goes16")`, a bucket dead since April 2025 — use the `data.py` path.

## 4. NOAA STAR real-time GOES imagery (cdn.star.nesdis.noaa.gov)

Ready-made JPEG/GIF/MP4/GeoTIFF/KMZ. Pattern (OBSERVED, live listings):
`https://cdn.star.nesdis.noaa.gov/<GOES19|GOES18>/ABI/<FD|CONUS|MESO/M1|SECTOR/<code>>/<PRODUCT>/<file>`

- Products FD: `01`–`16`, `AirMass`, `DMW`, `DayConvection`, `DayLandCloudFire`, `DayNightCloudMicroCombo`, `Dust`, `FireTemperature`, `GEOCOLOR`, `Sandwich`.
- Filenames `<YYYYDDDHHMM>_<SAT>-ABI-<SECTOR>-<PRODUCT>-<WxH>.jpg`; meso timestamps carry an **extra digit** (13 chars).
- Sizes: FD `339², 678², 1808², 5424², 10848², 21696²`; CONUS `416x250, 625x375, 5000x3000`; sector `300²–2400²`; meso `250²–2000²`.
- Every product dir has `latest.jpg`, `thumbnail.jpg`, and bare-size aliases (`678x678.jpg`) that are stable "latest at this size" URLs. FD `latest.jpg` is ~18.6 MB — use the aliases.
- No auth; `access-control-allow-origin: *`; `cache-control: max-age=0,s-maxage=600`.

**Important policy finding (OBSERVED):** `https://cdn.star.nesdis.noaa.gov/robots.txt` returns `User-agent: *` / `Disallow: /` — **the entire CDN is disallowed to crawlers.** By contrast `www.star.nesdis.noaa.gov/robots.txt` disallows only `/cgi-bin/`, `/thredds/`, `/tst/`, `/star/beta/`, `/intranet/`. INFERRED: use S3 for anything automated or bulk; reserve the CDN for low-volume display. Rate limits otherwise **UNCONFIRMED**.

**Live status note (OBSERVED):** a banner on https://www.star.nesdis.noaa.gov/GOES/conus.php?sat=G19 states that as of **2026-07-16 16:45 EDT** the site *"has restored production and delivery of GOES-East imagery from the GOES-19 ABI"*, with GLM and SUVI restoration still pending. The S3 buckets were unaffected.

## 5. EUMETSAT Data Store / EUMETView / Data Tailor

**Source caveat (OBSERVED):** two of three official doc surfaces were unusable during this research. `eumetsatspace.atlassian.net` (the docs wiki) returned HTTP 404 site-wide — *"Your Atlassian Cloud site is currently unavailable"* (retried 3× over ~20 min). `user.eumetsat.int` serves an identical 7,466-byte `... Loading ...` SPA shell for all guide URLs because its content loads from that same down wiki. **Findings below are grounded in live API responses and first-party source code instead**, which is stronger evidence than doc prose.

**Premise correction (OBSERVED):** `eumdac` is **not** on `github.com/eumetsat`. Canonical home is https://gitlab.eumetsat.int/eumetlab/data-services/eumdac (per PyPI `project_urls.Homepage`).

**Endpoints — from first-party `eumdac/endpoints.ini` v3.1.1 (OBSERVED):** `api = https://api.eumetsat.int`; `/token`, `/api-key`, `/data/browse/1.0.0`, `/data/download/1.0.0/collections/{cid}/products/{pid}`, `/data/search-products/1.0.0/os`, `/epcs` (Data Tailor), MQTT `subscribe.data.eumetsat.int:8883`.

**Auth:** OAuth2 **client_credentials with HTTP Basic on the token call** (OBSERVED, `eumdac/token.py::_update_token_data`), then `Authorization: Bearer`. Live: `GET /token` → 405 (POST-only); `POST /token` without Basic → **401 `{"error":"invalid_client"}`**. Gateway is WSO2.

**Account requirement is split (all OBSERVED via live probes):**

| Surface | Anonymous? |
|---|---|
| Browse API (`/data/browse/1.0.0/collections`) | **Yes** — 200, 184 collections; its OpenAPI has `"securityDefinitions": {}` |
| Search API (OpenSearch `/os`) | **Yes** — 200 with product features + download links |
| Download | **No** — 404 WSO2 fault unauthenticated (INFERRED a token is required) |
| Data Tailor `/epcs/*` | **No** — `/formats`, `/filters`, `/info`, `/customisations` all **401** |
| EUMETView WMS | **Yes, fully anonymous** |

Register at https://user.eumetsat.int/register; keys at https://api.eumetsat.int/api-key.

**EUMETView WMS — the zero-auth path.** Current endpoint **`https://view.eumetsat.int/geoserver/wms`** (OBSERVED, hard-coded in the portal's production JS bundle). Anonymity proven, not assumed: GetCapabilities → **200, 282,238 bytes**; anonymous GetMap for `mtg_fd:rgb_truecolour` → **200 image/png, 54,756 bytes**. 154 layers across workspaces `msg_fes` (25), `msg_iodc` (21), `msg_rss` (4), `mtg_fd` (18), `eps` (21), `copernicus` (15). Formats include `image/png`, `image/gif`, **`image/geotiff`**, PDF, KML/KMZ. WMS time dimensions state cadence directly (OBSERVED, captured 2026-07-26 ~19:15Z):

```
mtg_fd:vis06_hrfi   2024-09-16T02:40Z / 2026-07-26T18:50Z / PT10M
mtg_fd:li_afa       2025-05-30T15:00Z / 2026-07-26T19:00Z / PT5M
msg_fes:ir108       2020-09-01T00:00Z / 2026-07-26T18:45Z / PT15M
msg_rss:ir039_nrt   2020-02-12T14:40Z / 2026-07-26T19:00Z / PT5M
```

WMTS: GeoWebCache is deployed but `…/gwc/service/wmts?REQUEST=GetCapabilities` returned **HTTP 400 "Error getting coverage reader"** — general WMTS usability **UNCONFIRMED**.

**MTG/MSG status verified live (OBSERVED, real filenames ~19:15Z 2026-07-26):**

| Service | Collection | Platform | Cadence |
|---|---|---|---|
| FCI L1c FDHSI | `EO:EUM:DAT:0662` | MTI1 | **10 min** |
| FCI L1c HRFI | `EO:EUM:DAT:0665` | MTI1 | 10 min |
| LI L2 Flashes | `EO:EUM:DAT:0691` | MTI1 | 10 min file |
| SEVIRI 0° | `EO:EUM:DAT:MSG:HRSEVIRI` | MSG3 (Meteosat-10) | **15 min** |
| SEVIRI RSS | `MSG:MSG15-RSS` | MSG4 (Meteosat-11) | **5 min** |
| SEVIRI IODC | `MSG:HRSEVIRI-IODC` | MSG2 (Meteosat-9) | 15 min |

Cross-referenced against https://www.eumetsat.int/our-satellites/meteosat-series (OBSERVED, verbatim): Meteosat-12 *"primary operational satellite at 0 degrees providing full disc imagery every 10 minutes"*; Meteosat-9 *"imagery over the Indian Ocean. Operating until 2027"*. MTG-I2 launch planned April–September 2026.

**Resolutions — verbatim from live collection metadata (OBSERVED):** FCI FDHSI *"16 imaging spectral channels … 1km for visible and near-infrared … 2 km for infrared"*; FCI HRFI *"4 spectral channels … 0.5 km … 1 km for infrared"*. The classic SEVIRI 3 km / 1 km HRV figures **do not appear** in any retrieved collection abstract — **UNCONFIRMED as sourced**.

**Rate limits — one documented, verified limit only (OBSERVED, verbatim from the live OSDD at https://api.eumetsat.int/data/search-products/1.0.0/osdd):**
```xml
<param:Parameter name="c" value="{count}" minimum="0" minInclusive="0"
                 maxExclusive="501" title="Number of records to return"/>
```
→ **max 500 products per search request.**

**Throttling: UNCONFIRMED, and the circulating numbers actively conflict** — snippets attribute *30 req/s, 5 TB/day, 10 parallel* to the FAQ but *40–45 req/s, 10 TB/day, 15 parallel* to the Release Changelog. Neither primary page was loadable; they disagree by ~2×. **Asserting neither.**

**Data Tailor quotas — be blunt: `eumdac` contains no hard-coded quota numbers.** Quota is server-side per-user via `GET /epcs/report_quota`; the CLI prints **`"No quota limit set in the system"`** when `disk_quota_active` is false (OBSERVED). The circulating **"3 concurrent jobs / 20 GB workspace"** appears only as a search-engine snippet of the unloadable FAQ: **UNCONFIRMED, do not cite.**

**Formats from real manifests (OBSERVED):** MSG SEVIRI `HRSEVIRI` → ZIP containing `.nat` native + metadata, ~140 MB per 15-min full disc. FCI L1c FDHSI → 61 sip-entries, all netCDF4-enhanced chunked, ≈663 MB/cycle. GRIB2 and BUFR are live MTG L2 formats (`EO:EUM:DAT:0800` Cloud Mask GRIB2, `0799` All Sky Radiance BUFR). HDF5: **no evidence found — UNCONFIRMED**.

**Python:** `eumdac` v3.1.1 (2025-12-11, PyPI + conda-forge, GitLab). `satpy` reader maturity read directly from the YAML (OBSERVED): `seviri_l1b_native` = **Nominal**, `fci_l1c_nc` = **Beta**, `li_l2_nc` = **Beta**. **`eumartools` premise correction (OBSERVED):** not on PyPI (404); distributed via anaconda.org/cmts/eumartools, source at gitlab.com/benloveday — a personal repo of a EUMETSAT staffer, not first-party.

## 6. Copernicus Data Space Ecosystem (CDSE) — the Sentinel free tier

**Data:** live query `GET https://stac.dataspace.copernicus.eu/v1/collections?limit=1000` returned **422 collections** (OBSERVED) — Sentinel-1 (grd/slc/ocn/etad/mosaics), Sentinel-2 (l1c/l2a/mosaics), Sentinel-3 (OLCI/SLSTR/SRAL/SYN with explicit `-nrt`/`-stc`/`-ntc`), Sentinel-5P (L1 bands 1–8, L2 NO2/SO2/CO/CH4/HCHO/O3), Sentinel-6, Copernicus DEM, Landsat C2 L1, **47 MODIS collections**, ~300 CLMS collections in COG and netCDF variants.

**Auth (all OBSERVED, live):**
- **Catalogue search is anonymous** — OData `?$top=1` → 200 with product JSON, no token; `stac.dataspace.copernicus.eu/v1/` → 200 unauthenticated.
- **Download and S3 are not** — `eodata.dataspace.copernicus.eu/` → **403**; `sh.dataspace.copernicus.eu/…` → **401**.
- Free account required for download; registration + email verification, optional 2FA.
- **Oddity (OBSERVED):** the classic resto/OpenSearch path `catalogue.dataspace.copernicus.eu/resto/api/collections/Sentinel2/search.json` returned **403** while OData and STAC returned 200. **UNCONFIRMED** whether OpenSearch now requires auth or moved.
- Token **10 min**, refresh **60 min** (OBSERVED, Quotas.html). SH auth docs warn verbatim: *"Do not fetch a new token for each API request… Token requests are rate limited."*

**Exact free-tier quotas — "Copernicus General Users" (OBSERVED verbatim, https://documentation.dataspace.copernicus.eu/Quotas.html):**

| Limit | S3/OData/STAC | Data Workspace | openEO | Sentinel Hub | Direct HTTP to COGs |
|---|---|---|---|---|---|
| Requests/month | – | – | – | **10 000** | 50 000 |
| Requests/minute | 2000 (S3 only) | – | 12 | **300** | – |
| **PU/month** | – | – | – | **10 000** | – |
| PU/minute | – | – | – | 300 | – |
| Bandwidth/connection | 20 MB/s | – | – | – | – |
| Concurrent connections | 4 | – | 2 | – | – |
| Monthly transfer (IAD) | **12 TB** | – | – | – | – |
| Monthly transfer (DAD) | – | 0.1 TB | – | – | – |
| Processed products/month | – | 25 | – | – | – |
| Credits/month | – | – | **10 000** | – | – |

On exceeding 12 TB: *"the maximum bandwidth drops to 1MB/s and the number of concurrent connections drops to 1."* Accounting gotcha (verbatim): *"Each recursive file download counts as individual S3 requests for quota purposes."*

**openEO credits caveat (OBSERVED):** Quotas.html footnote 15 labels the 10,000 figure a *"Temporary Boost… to 10 000"* citing a 2024-09-03 news item — **nearly two years stale, though still shown on the live page today. Verify before relying on it.** Credit model: synchronous requests cost a flat **7 credits**, batch jobs a flat 2 overhead. Rate limits: **12 requests/minute** (*"1 request per 5 seconds"*), 2 concurrent processing, 2 concurrent API requests.

**Sentinel Hub Batch is NOT free — two independent official confirmations (OBSERVED):**
1. Quotas.html footnote 8: *"Note that there are APIs that are not available to Copernicus General Users such as Sentinel Hub Batch Processing API."*
2. BatchV2.html: *"The BatchV2 API is only available for users with Copernicus Service user Accounts."*

**PU accounting (OBSERVED, https://docs.sentinel-hub.com/api/latest/api/overview/processing-unit/):** multiplicative — `(output_px / 262144) × (n_bands / 3) × format_factor × n_data_samples × ortho_factor`. Worked example: 2000×2000 px, 2 bands, 16-bit TIFF, orthorectified = **20.34 PU**. Process API output capped at **2500 px per side** — INFERRED, this is the structural reason large-AOI work forces Batch, which the free tier does not grant. **Practical ceiling (INFERRED, arithmetic from two OBSERVED figures):** 10,000 PU ÷ 20.34 ≈ **~490 requests of 2000×2000 2-band ortho per month.** Not a documented number.

**S5P gotcha (OBSERVED, verbatim):** *"openEO and Sentinel Hub users can process only one Sentinel-5P band simultaneously; attempting to load multiple product types simultaneously will generate an error."*

**IAD vs DAD (OBSERVED, verbatim):** *"It is not possible to order DAD by using OData, STAC or S3, Copernicus Browser or any of the Sentinel Hub APIs. DAD (Offline data) can only be ordered by using the Data Workspace."* INFERRED: archive completeness ≠ instant downloadability.

**The load-bearing `sentinelhub-py` config (OBSERVED)** — defaults point at the *commercial* deployment:
```python
config.sh_base_url  = "https://sh.dataspace.copernicus.eu"
config.sh_token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
config.save("cdse")   # then SHConfig("cdse")
```
Gotcha (OBSERVED): setting `sh_base_url` alone is not always enough — `DataCollection` objects carry their own `service_url`; CDSE examples redefine them via `DataCollection.SENTINEL2_L2A.define_from(name="s2l2a", service_url="https://sh.dataspace.copernicus.eu")`.

**`pystac-client` against CDSE must call `cat.add_conforms_to("ITEM_SEARCH")`** — the API doesn't advertise item-search conformance (OBSERVED).

## 7. Sentinel Hub commercial vs CDSE free — the 2026 branding state

**OBSERVED:** `https://www.sentinel-hub.com/pricing/` returns 200 but the body is only *"Redirecting…"* → `https://www.planet.com/pricing/`. Planet's docs place Sentinel Hub inside the **"Planet Insights Platform"**, billing via `insights.planet.com/account`. Staleness warning: much of the surviving sentinel-hub.com FAQ still carries the pre-acquisition footer *"Owned and Operated by Sinergise Solutions d.o.o., Ljubljana"* — treat its numbers as possibly stale.

**Not in CDSE:** PlanetScope/SkySat/Planetary Variables, Maxar (OBSERVED — commercial subscription only). Airbus Pléiades/SPOT **UNCONFIRMED**. Landsat 1–7 archive + HLS are on SH US-West-2 only. **MODIS is the real trap:** 47 MODIS collections exist in the CDSE STAC catalogue but MODIS is **absent from CDSE's Sentinel Hub data page** — downloadable via STAC/S3, not renderable through Process API.

**Trial still exists in 2026 (OBSERVED):** 30 days via https://insights.planet.com/sign-up, no credit card, 30,000 PU. Verbatim: *"The trial account is limited to 30,000 requests and 300 processing units per minute… does not provide access to TPDI functionality… does not provide access to the batch API."*

*Hypothesis check:* the researching agent hypothesised the trial had been discontinued post-acquisition; disconfirming evidence found (live sign-up + trial terms on Planet's domain). The alternative explanation for the pricing redirect — billing consolidation, not discontinuation — is what the docs support.

**Exact 2026 plan names and prices: UNCONFIRMED** — both pricing pages render as empty JS shells to fetchers and raw curl. **No dollar figures were verifiable; none are given.**

## 8. USGS EarthExplorer / M2M + Landsat on AWS + LandsatLook

**LandsatLook STAC is the free, anonymous path — use this first.** `https://landsatlook.usgs.gov/stac-server`, STAC 1.1.0, conforms to STAC API core/collections/OGC Features/item-search + CQL2. **Anonymous confirmed:** `GET /stac-server/search?limit=1` → **HTTP 200 with items, no credentials** (OBSERVED). 18 collections including `landsat-c2l1` (temporal extent **1972-07-25 → present**), `landsat-c2l2-sr`/`-st`, `landsat-c2ard-*`, `landsat-c2l3-{fsca,ba,dswe}`, `eo-1-*`.

**Key relationship (OBSERVED):** every asset carries **both** a free anonymous HTTPS `href` under `https://landsatlook.usgs.gov/data/…` **and** an `alternate.s3.href` of `s3://usgs-landsat/…`. INFERRED rule: **metadata + HTTPS delivery are free and anonymous; only direct S3 reads incur requester-pays.**

**The `usgs-landsat` requester-pays trap (OBSERVED, two independent sources):** anonymous list returns HTTP 403 with `<Message>Anonymous users cannot invoke requests against Requester Pays buckets. Please authenticate.</Message>`; USGS confirms *"s3://usgs-landsat [requester pays] bucket within the Oregon us-west-2 region."* This also bites **Earth Search** — its `landsat-c2-l2` assets point at that bucket, so Landsat *search* is free but Landsat *pixels* via S3 need an AWS account. Sentinel-2 has no such catch. Set `RequestPayer='requester'` / `AWS_REQUEST_PAYER=requester` only on the S3 alternates. Old `landsat-pds` returns a plain 403 — INFERRED retired, exact date **UNCONFIRMED**.

**M2M API** — `https://m2m.cr.usgs.gov/api/api/json/stable/`, *"a RESTful JSON API for accessing more than 300 unique USGS/EROS datasets"* (OBSERVED). The API docs root is **behind ERS login** (302 → ers.cr.usgs.gov/login).
- **`login` (password) deprecated 2025-02-26 → `login-token`** (OBSERVED; MEDIUM confidence on exact date).
- **Application token (OBSERVED, verbatim from https://www.usgs.gov/media/files/m2m-application-token-documentation):** *"The application token is a 64-bit encrypted string… Each user is allowed **up to 10** of these tokens."* Value is cleared from screen after 60 seconds and is unrecoverable.
- **Separate access approval IS required (OBSERVED, verbatim, https://code.usgs.gov/eros-user-services/machine_to_machine):** *"To submit download requests through the M2M endpoint, users need an active EROS Registration Service (ERS) account and will need to request access to the endpoint."* Review 24–48 business hours (MEDIUM confidence).
- **Rate limits: UNCONFIRMED** — no published numeric limit on any login-free USGS source.

**Mission facts (OBSERVED):** L9 launched 2021-09-27, OLI-2 9 bands @30 m + pan @15 m, TIRS-2 ≥100 m resampled to 30 m, **16-day repeat**; **L8+L9 combined = 8-day revisit**. Latency: L9 → Tier 1/2 *"within 4-6 hours of acquisition"*, Level-2 *"within 3 days"*. **Landsat 7 decommissioned 2025-06-04.** **Landsat Next restructured as "Landsat 10"** — now a **single satellite** (not the triplet), launch *"expected in 2031"*, 26 bands, 10–20 m VNIR/SWIR, **18-day revisit**. The older "6-day revisit trio" description is superseded. **Sentinel-2 is no longer mirrored by USGS** — ingest stopped 2022-10-19, archive removed 2022-11-18; use CDSE.

**Python:** `pystac-client` 0.9.0 (anonymous against landsatlook) · **`landsatxplore` 0.15.0 — last release 2023-04-11**, predates the Feb-2025 auth deprecation, open upstream issue "Update api login to use login-token url" → **treat as likely broken** · **`usgs` (kapadia/usgs) 0.3.7 released 2026-05-18** — actively maintained, the safer M2M wrapper.

## 9. Himawari-8/9 on AWS + JMA/NICT/JAXA

**AWS (OBSERVED, https://registry.opendata.aws/noaa-himawari/ + live probes):** `noaa-himawari8`, `noaa-himawari9`, both us-east-1, **fully anonymous, NOT requester-pays**. Licence verbatim: *"NOAA and JMA request attribution for the use or dissemination of unaltered data."*

**Keys and formats (OBSERVED, real keys):**
```
AHI-L1b-FLDK/2026/07/25/0000/HS_H09_20260725_0000_B01_FLDK_R10_S0101.DAT.bz2
AHI-L2-FLDK-Clouds/2026/07/01/0000/AHI-CMSK_v1r1_h09_s…_e…_c….nc
```
→ **L1b = JMA HSD `.DAT.bz2`, 10 segments `S0101`…`S1010`; L2 = netCDF4.** Cadence (OBSERVED, registry): Full Disk **10 min**; Regions 1–3 **2.5 min**; Regions 4–5 **0.5 min**.

**Two gotchas, both OBSERVED:**
1. `noaa-himawari9/AHI-L2-FLDK-SST/` is an **empty prefix (KeyCount 0)** — there is no SST product for H9 on AWS. Porting an H8 SST pipeline to H9 yields silent empty results.
2. **Archive coverage is not what you'd assume.** H9 FLDK: 2022-10-28 → 2026-07-26, continuous. H8 FLDK: 2015-07-07 → 2022 continuous, **nothing 2023–2024**, then **only 2025-10-11 → 2025-11-26** — and H9 has **no days between 2025-10-12 and 2025-11-25**, exactly complementary. INFERRED: H8 came out of standby to cover an H9 outage. **Alternative explanation not excludable:** a selective NODD re-ingest for unrelated reasons; JMA's switchover page lists nothing after Dec 2022 — **UNCONFIRMED**. Date-range queries that blindly union both buckets will double-count this window.

**Satellite status 2026 (OBSERVED, https://www.data.jma.go.jp/mscweb/en/oper/status.html):** **Himawari-9 — 140.7°E, "Operational" since 2022-12-13. Himawari-8 — 140.7°E, "Standby."** H8 is backup, not retired.

**JMA portal — the commonly-cited URL is dead.** `https://www.jma.go.jp/bosai/en_himawari/` returns **HTTP 404** (OBSERVED, both curl-with-browser-UA and WebFetch), as does `/bosai/himawari/`. But the **data paths are live** (OBSERVED): `…/bosai/himawari/data/satimg/targetTimes_fd.json` → `{"basetime":"20260725071000",…}` (10-min steps), and tiles at `…/satimg/{basetime}/{area}/{validtime}/{band}/{type}/{z}/{x}/{y}.jpg`, verified 200, no auth. **Undocumented/unofficial — treat as unstable.** JMA terms of use **UNCONFIRMED**.

**NICT Himawari Real-time Web** — https://himawari8.nict.go.jp/ (200, OBSERVED). `…/img/D531106/latest.json` → `{"date":"2026-07-26 18:50:00","file":"PI_H09_…_TRC_FLDK_R10_PGPFD.png"}` — note **`H09`**. Tiles at `/img/D531106/{level}/{tilesize}/{YYYY}/{MM}/{DD}/{HHMMSS}_{x}_{y}.png`, no auth. **Terms of use UNCONFIRMED** — no explicit ToU found; API undocumented, so self-rate-limit.

**JAXA P-Tree** — registration required, rights granted manually (*"may take a couple of days"*). **Key contrast with AWS (OBSERVED, verbatim, https://www.eorc.jaxa.jp/ptree/faq.html):** *"those data that has passed over 30 days has been deleted from the P-Tree FTP server."* P-Tree keeps ~30 days; the NOAA buckets hold the multi-year archive. **Licence conflict — flag for legal review (OBSERVED, two JAXA pages disagree):** the FAQ says *"Data from February 1, 2026 (00:00 UTC) onward are available for commercial use"* while https://www.eorc.jaxa.jp/ptree/terms.html (2nd ed., June 2018) still says use is *"limited to non-profit purposes such as research and education"* and *"you cannot redistribute the data to the third parties."* The FAQ is newer.

**Python:** `satpy` 0.60.0 reader `ahi_hsd` matches the `.DAT.bz2` files exactly. `pyspectral` 0.14.3 — AHI true colour needs `HybridGreen` (~15% B04 + 85% B02) because AHI's green band sits at 0.51 µm. `s3fs` with `anon=True` — **no `RequestPayer` needed**, unlike `usgs-landsat`.

## 10. Microsoft Planetary Computer

**Status verification — the important 2026 finding.** The free hosted JupyterHub **was retired on 2024-06-06**, not 2026 (OBSERVED, https://github.com/microsoft/PlanetaryComputer/discussions/347): *"the Planetary Computer Hub will be retired on the 6th of June 2024"* and *"the Planetary Computer Data and APIs will remain available and unchanged."* **There is no free compute tier any more** — official guidance is bring-your-own-compute (OBSERVED).

**The data + APIs are still live and free.** Live calls 2026-07-26 (OBSERVED): `GET https://planetarycomputer.microsoft.com/api/stac/v1` → `{"type":"Catalog","id":"microsoft-pc",…}`; `/collections` → **135 collections** (landsat-c2-l2, sentinel-1-rtc, cop-dem-glo-30, goes-cmi, daymet-*, 3dep-lidar-*, io-lulc-annual-v02…). Catalog repo last commit 2026-06-26. No deprecation notice found for the public catalog (OBSERVED absence — treat as "no announced sunset", not a guarantee). Service is still labelled a Preview.

**The access model, verified empirically (OBSERVED):** docs say *"The STAC metadata API is available to all users and does not require an account… All data assets require a token"* and *"Datasets in the Planetary Computer are anonymously accessible: you don't need to supply a subscription key to get a SAS token."* Live proof: unsigned blob GET → `HTTP 409 PublicAccessNotPermitted`; anonymous token request `GET /api/sas/v1/token/landsateuwest/landsat-c2` → **HTTP 200** with `"msft:expiry"` ~45 min out. **INFERRED: no dataset is anonymously readable at the blob URL; every dataset's token is anonymously obtainable.** Net effect — effectively zero-signup, one extra signing call per asset.

**Rate limits:** docs state the mechanism but not the numbers — limits depend on West-Europe origin and whether a subscription key is supplied; *"These limits should be generous"*; *"Most data can be downloaded anonymously, but will be throttled."* **Exact figures UNCONFIRMED** (no `RateLimit-*` headers returned — checked live).

**Python:** `planetary-computer` 1.0.0, **MIT** (OBSERVED, PyPI). `planetary_computer.sign_inplace` as a `pystac-client` modifier. Optional `PC_SDK_SUBSCRIPTION_KEY` *"for API access with fewer rate limits."* Pure-REST alternative: STAC search, then `GET /api/sas/v1/sign?href=<blob url>`, then curl the signed href (INFERRED from documented endpoints).

**Planetary Computer Pro is a different, paid product** — Azure GeoCatalog resource, Entra ID auth, meters for Ingest/Transform (per vCPU hour), Geospatial Data Operations (per 10K ops), Bandwidth (per GB), Storage (per GB/month). **Exact rates UNCONFIRMED** — the pricing page renders `$-` placeholders. **Key distinction for an agent: Pro is for hosting *your own* data. It gives you no access to the free public catalog, and the free catalog costs nothing and needs no Azure account** (INFERRED).

## 11. Google Earth Engine — free for noncommercial, but 2026 added hard quotas

**Licensing (OBSERVED, https://earthengine.google.com/noncommercial/):** *"Earth Engine will remain free of charge for nonprofit organizations using the services for scientific research, education, or noncommercial activities"*; also free for students/faculty/staff, journalists, trainers, and *"individual developer[s] using Earth Engine for noncommercial purposes."* Government is narrow: free only for UN-defined Least Developed Countries, recognized Indigenous Governments, or scholarly research. Blanket bar on *"fee-for-service activities"* (ToS §2.1). *"Unpaid commercial use of Earth Engine is not allowed by our terms of service."*

**NEW in 2026 — noncommercial tiers, effective 2026-04-27 (OBSERVED, https://developers.google.com/earth-engine/guides/noncommercial_tiers):**

| Tier | Monthly free quota | Billing account? |
|---|---|---|
| Community (default) | **150 EECU-hours** (540,000 EECU-s) | No |
| Contributor | **1,000 EECU-hours** | Yes — *"you won't be charged for Google Earth Engine noncommercial usage"* |
| Partner | **100,000 EECU-hours** | Not stated (UNCONFIRMED); application + review |

Quota resets monthly, no carryover; rollout *"still gradually rolling out."* Over quota → **restricted mode**: *"you can still use Earth Engine, but it'll be in restricted mode… limits your online and batch concurrency."* Degradation, not cutoff.

**Headless auth (the agent path) — service account (OBSERVED, https://developers.google.com/earth-engine/guides/service_account):**
```python
creds = ee.ServiceAccountCredentials('sa@proj.iam.gserviceaccount.com', '.private-key.json')
ee.Initialize(creds, project='my-project')
```
Required IAM role name: UNCONFIRMED. `earthengine-api` 1.7.36, Apache-2.0, Python ≥3.10.

**Quotas (OBSERVED, https://developers.google.com/earth-engine/guides/usage):** 40 concurrent requests; *"100 requests/s (6000 requests/min)"*; ~2 concurrent batch tasks; 250 GB asset storage; 10,000 assets; 3,000 task queue; 10 MB payload. *"Attempting to circumvent quota restrictions through the use of multiple Google Accounts is a violation of the Earth Engine Terms of Service."*

**Commercial $ rates: UNCONFIRMED** — `cloud.google.com/earth-engine/pricing` is JS-rendered and could not be read. No figures invented.

## 12. AWS Open Data & Earth Search — the lowest-friction path

**Anonymous access, official (OBSERVED, https://docs.aws.amazon.com/cli/latest/reference/s3/ls.html):** `--no-sign-request` — *"Do not sign requests. Credentials will not be loaded if this argument is provided."* Requester-pays: `--request-payer requester`.

**Bucket verification (live anonymous S3 REST, 2026-07-26):**

| Bucket | Anonymous LIST | Note |
|---|---|---|
| `sentinel-cogs` (us-west-2) | 200; ranged GET 206 | Sentinel-2 L2A COGs, no AWS account |
| `sentinel-s2-l2a` (eu-central-1) | 200; JP2 GET 206 | **Not requester-pays today** — contradicts the common assumption |
| `usgs-landsat` | **403** requester-pays | needs SigV4 + `--request-payer requester` |
| `noaa-goes16`, `noaa-goes18/19` | 200 | GOES ABI |
| `noaa-gfs-bdp-pds`, `noaa-hrrr-bdp-pds` | 200 | NWP GRIB2 |
| `nex-gddp-cmip6` | 200 | **correct name**; `nasa-nex-gddp-cmip6` → `NoSuchBucket` |
| `copernicus-dem-30m` | 200 | Copernicus DEM |

**Earth Search (Element 84)** — `https://earth-search.aws.element84.com/v1`, *"a free-to-use STAC API"* (OBSERVED, https://element84.com/earth-search/). **9 collections, live:** `sentinel-2-l2a`, `-l1c`, `-c1-l2a`, `-pre-c1-l2a`, `sentinel-1-grd`, `landsat-c2-l2`, `naip`, `cop-dem-glo-30`, `cop-dem-glo-90`. **Anonymous, no key** — unauthenticated search returned same-day item `S2B_21WWV_20260726_0_L2A` with asset `red` → `sentinel-cogs` COG; anonymous ranged GET → **HTTP 206** (OBSERVED, live). Rate limits / formal ToS: **UNCONFIRMED** (none published).

**Canonical zero-auth agent pipeline:**
```bash
uv pip install pystac-client odc-stac rioxarray
```
```python
import pystac_client, odc.stac
c = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
items = c.search(collections=["sentinel-2-l2a"], bbox=bbox, datetime="2026-06/2026-07").item_collection()
xx = odc.stac.load(items, bands=["red","green","blue"], resolution=10)
```
Or pure `curl` + `jq` against `/search` — zero credentials, zero install.

## 13. openEO

`pip install openeo` (PyPI 0.51.0, Apache-2.0). CDSE backends: `https://openeofed.dataspace.copernicus.eu/` (federated) and `https://openeo.dataspace.copernicus.eu/` (avoids partner resources). *"Basic discovery of openEO collections and processes is possible without authentication, executing openEO workflows requires user authentication"* (OBSERVED). Device-code OIDC prints a URL for a browser — **agent-hostile unless a refresh token or client-credentials pair is pre-provisioned** (INFERRED). Quotas as in §6.

## 14. Geospatial Python tooling — versions/licences OBSERVED from PyPI + repo LICENSE, 2026-07-26

| Package | Version | Licence | Role | Creds |
|---|---|---|---|---|
| pystac | 1.15.1 | Apache-2.0 | STAC object model | none |
| pystac-client | 0.9.0 | Apache-2.0 | search STAC APIs; ships a **`stac-client` CLI** | none |
| odc-stac | 0.5.2 | Apache-2.0 | STAC items → `xarray.Dataset`, Dask | none |
| stackstac | 0.5.1 | MIT | STAC items → 4-D DataArray | none |
| rioxarray | 0.22.0 | Apache-2.0 | `.rio` accessor: CRS, clip, reproject | none |
| xarray | 2026.7.0 | Apache-2.0 | N-D labelled arrays | none |
| satpy | 0.60.0 | **GPL-3.0-or-later** | native L1 sensor readers (SEVIRI/ABI/AHI/VIIRS) | none; **does not download** |
| earthaccess | 0.18.0 | MIT | NASA CMR search + download/stream | **EDL** |
| sentinelhub | 3.11.5 | MIT | SH Process/Catalog/Statistical APIs | **OAuth** |
| leafmap | 0.63.0 | MIT | interactive mapping; `pc` module | none |
| geemap | 0.38.3 | MIT | GEE + ipyleaflet | **GEE account** |
| titiler.core | 2.2.0 | MIT | dynamic tile server (COG/STAC/MosaicJSON) | none |

**Notable, all OBSERVED:**
- **`pip install titiler` is dead**: *"Do not install the package named `titiler` from PyPI. In late 2025, we dropped support for this metapackage"* — use `titiler.core` / `titiler.application`.
- **satpy is the only GPL package here** — matters for a distributed commercial product.
- **Python floor is rising:** rioxarray, earthaccess, geemap now require **≥3.12**.
- **stackstac looks unmaintained:** last release and last repo push both 2024-08-10; its own README says *"I haven't even written tests yet! Don't use this in production"* and documents *"Single-band raster data only!"*. **odc-stac** (pushed 2026-07-22, multi-band) is the safer 2026 default — OBSERVED facts, recommendation INFERRED.
- **pystac Spring 2026 breaking change:** *"our extension implementations have moved to their own Python packages"* (e.g. `pystac-ext-projection`).

---

# PART II — WEATHER & FORECAST DATA

## 15. Open-Meteo — the best free weather API for an agent

**Rate limits (free / non-commercial), cross-referenced across two of their own pages (OBSERVED):**
- Pricing page (https://open-meteo.com/en/pricing): **600 calls/min, 5,000/hour, 10,000/day, 300,000/month**.
- Terms page (https://open-meteo.com/en/terms), in prose: *"Less than 10'000 API calls per day, 5'000 per hour and 600 per minute."*
- GitHub README: *"If your application exceeds 10'000 requests per day, please contact us."*
- INFERRED: the daily and monthly figures are the same ceiling (10k × 30 = 300k) — no extra monthly headroom.

**No API key** (OBSERVED) — key *"Only required to commercial use to access reserved API resources for customers."* Verified live:
```bash
curl "https://api.open-meteo.com/v1/forecast?latitude=52.52&longitude=13.41&current=temperature_2m"
# → HTTP 200, {"current":{"time":"2026-07-26T19:00","temperature_2m":20.2}}
```

**⚠ THE BIGGEST GOTCHA — commercial use is excluded (OBSERVED).** The pricing table marks commercial use ❌ for the free tier; terms define non-commercial as *"private or non-profit websites or apps that do not have subscriptions or advertising"*, and commercial as *"websites or apps that have subscriptions or display advertisements."* **For anything sold to clients, the free tier does not apply.**

**APIs (OBSERVED, https://open-meteo.com/en/docs):** Weather Forecast (16 days), Historical Weather, Ensemble Models, Seasonal Forecast, Climate Change, Marine, Air Quality, Satellite Radiation, Flood, Geocoding & Elevation. That the historical API is specifically ERA5-backed is **UNCONFIRMED** from the pages fetched; the PyPI page says data goes *"back to 1940"*, the ERA5 start year — INFERRED.

**Models (OBSERVED):** ECMWF IFS (9–25 km, 15 day), NOAA GFS/HRRR (3–25 km), Météo-France ARPEGE/AROME (1–25 km), DWD ICON (2–11 km), UK Met Office (2–10 km), JMA, KMA, GEM — *"20+ national weather models."*

**Formats:** JSON, CSV, XLSX, FlatBuffers. **Python:** `openmeteo-requests` 1.7.5 (2026-01-19), MIT, Python 3.9–3.14; zero-copy FlatBuffers into numpy/pandas/polars; integrates `requests-cache` (1-hour expiry recommended).

**Licensing split (OBSERVED):** server **code is AGPLv3-or-later**; the **data is CC BY 4.0**. Self-hosting via Docker Compose is supported — but AGPL means a modified self-hosted network service triggers source-disclosure obligations (INFERRED).

**No uptime guarantee (OBSERVED):** *"The accuracy and completeness of the data products and their uninterrupted provision are not guaranteed by Open-Meteo."*

## 16. NOAA/NWS `api.weather.gov`

**Auth: User-Agent only (OBSERVED, https://www.weather.gov/documentation/services-web-api):** *"A User Agent is required to identify your application. This string can be anything, and the more unique to your application the less likely it will be affected by a security event."* Example: `User-Agent: (myweatherapp.com, contact@myweatherapp.com)`. No key, no registration.

**Rate limits — deliberately undisclosed (OBSERVED, verbatim):** *"The rate limit is not public information, but allows a generous amount for typical use. If the rate limit is exceeded a request will return with an error, and may be retried after the limit clears (typically within 5 seconds)."* Any specific number seen elsewhere is third-party guesswork — **UNCONFIRMED by definition.**

**Endpoints:** `/points/{lat},{lon}` → returns the grid + forecast URLs; `/gridpoints/{office}/{gridX},{gridY}/forecast`; `/gridpoints/{wfo}/{x},{y}/stations`; `/alerts/active?area={state}`. Full spec at `https://api.weather.gov/openapi.json`. Verified live:
```bash
curl -A "(myapp, me@example.com)" "https://api.weather.gov/points/38.8894,-77.0352"   # → 200 application/geo+json
```

**Formats:** GeoJSON (default), JSON-LD, DWML, OXML, **CAP** (`application/cap+xml`), ATOM. `/alerts` holds the past seven days; NCEI is the historical archive. Caveat quoted: alerts do **not** include SPC Tornado Watch language — *"Tornado Watch alerts are derived directly from the local WFO's WCN product."*

**Coverage: US only**, grids ~2.5 km per WFO.

## 17. ECMWF Open Data — best *commercially usable* free forecast source

**What's free (OBSERVED, https://www.ecmwf.int/en/forecasts/datasets/open-data):** *"A subset of ECMWF real-time forecast data from the IFS and AIFS models is made available to the public free of charge."* *"Products are available at 0.25 degrees resolution in GRIB2 format unless stated otherwise."* GRIB2 uses CCSDS compression since July 2023 — your reader must support it.

**Licence — cross-referenced across three primary sources (OBSERVED):** CC-BY-4.0 + ECMWF Terms of Use, and critically *"the data may be redistributed and used **commercially**, subject to appropriate attribution"* (ECMWF page, the `ecmwf-opendata` repo, and https://registry.opendata.aws/ecmwf-forecasts/ all agree). **This is the notable contrast with Open-Meteo's free tier.**

**Runs/steps (OBSERVED):** four cycles daily (00/06/12/18 UTC) for both IFS and AIFS. 00z/12z: 0–144 h at 3-h steps, then 150–360 h at 6-h. 06z/18z: 0–144 h only.

**Retention (OBSERVED):** *"Data are retained for the most recent 12 forecast runs, corresponding to approximately 2–3 days."* **It is a real-time feed, not an archive** — pull and store it yourself.

**Latency (OBSERVED, two statements):** *"IFS data are released at the end of the real-time dissemination schedule. AIFS data are released as soon the data are produced"*; the client repo says *"Data is available between 7 and 9 hours after the forecast starting date."* INFERRED: AIFS is faster.

**The only exact documented rate limit in this entire survey (OBSERVED):** *"Access to the Open-Data Portal is currently limited to **500 simultaneous connections**"* (applies to `data.ecmwf.int`; ECMWF recommends the cloud mirrors if you hit it). No documented per-request throttle on the S3 mirror (UNCONFIRMED).

**AWS mirror:** bucket `ecmwf-forecasts`, **eu-central-1**, not requester-pays, anonymous listing verified 200. Contents live 2026-07-26: `20260726/00z/{ifs,aifs-single,aifs-ens}/…` — **IFS HRES + ENS and AIFS deterministic + ensemble are all in the free stream in 2026** (OBSERVED).

**⚠ ECMWF's own docs are wrong about the Azure mirror (OBSERVED).** The open-data page lists `ai4edataeuwest.blob.core.windows.net/ecmwf/`; probing anonymously returns **HTTP 409 `PublicAccessNotPermitted`**. That path requires a Planetary Computer SAS token. Use AWS eu-central-1 or `data.ecmwf.int`.

**Python:** `pip install ecmwf-opendata`, Apache-2.0. Streams `oper`, `enfo`, `wave`, `scda`/`scwv`.

## 18. Copernicus CDS / ADS (ERA5, CAMS)

Free but **account-gated** (OBSERVED, https://cds.climate.copernicus.eu/how-to-api): *"If you do not have an account yet, please register"*; *"One must agree to the Terms of Use of a dataset before downloading."* `pip install "cdsapi>=0.7.7"`, credentials in `$HOME/.cdsapirc`. Endpoints: CDS `https://cds.climate.copernicus.eu/api`, ADS `https://ads.atmosphere.copernicus.eu/api`. A newer `ecmwf-datastores-client` exists, *"Incubating"*, and users *"are not requested to migrate."*

**Queue / rate limits: UNCONFIRMED** — neither how-to-api page states any quota, queue depth, or volume cap; no official limits page found. Requests are known to queue but no primary-source number exists.

**CLI-agent verdict:** poor for interactive use — async job submission + queueing + credential file + NetCDF/GRIB output. Right for batch reanalysis, wrong for "what's the weather".

## 19. MET Norway `api.met.no` — best global keyless option

All OBSERVED from the official ToS (https://api.met.no/doc/TermsOfService):
- **User-Agent required**: *"All requests must (if possible) include an identifying User Agent-string (UA)… with the application/domain name."* Risk of being blocked without warning if absent.
- **Rate limit**: *"Anything over 20 requests/second per application (total, not per client) requires special agreement."* 429 on enforcement. Note it is **per application, not per client** — a distributed deployment shares the budget (INFERRED).
- **Caching is mandatory, not optional**: *"Cache data locally and use the `If-Modified-Since` request header."* *"Web servers and mobile apps should cache all API responses."* Mobile apps must not poll more than once per 10 minutes.
- **Coordinate precision trap**: truncate to max 4 decimals; *"requests with 5+ decimals return 403 Forbidden."* This bites naive lat/lon passthrough.
- **Licence**: CC BY 4.0, attribution required. Do not use "Yr" in service names.
- HTTPS only.

Locationforecast is the flagship (global, JSON); Nowcast/radar are Nordic. Exact product list, non-JSON formats, and Nowcast extent: **UNCONFIRMED** (per-product doc pages not fetched). No official Python package found — **UNCONFIRMED** whether one exists; plain curl works.

## 20. OpenWeatherMap (2026)

**Free tier (OBSERVED, https://openweathermap.org/price):** *"60 API calls/minute, 1,000,000 calls/month."* Included free: Current Weather API, **3-hour Forecast (5 days)** — **yes, the classic 5-day/3-hour forecast is still free in 2026** — plus Air Pollution API, Weather Maps (15 layers), Geocoding API.

**One Call is where 2026 differs from older write-ups (OBSERVED):**
- One Call 3.0 still exists but *"is included in the 'One Call by Call' subscription only"* — a **separate subscription**, with 1,000 calls/day free within it (https://openweathermap.org/api/one-call-3).
- There is now a **One Call API 4.0**: *"We recommend using One Call API 4.0 for all new integrations"*; pay-per-call with 1,000 daily free calls.
- **Credit-card requirement: UNCONFIRMED.** Neither page states a card is mandatory for the free allowance. Widely reported elsewhere; no primary-source statement found, so not asserted.

## 21. Tomorrow.io — free-tier numbers could not be confirmed

**Exact free-tier limits: UNCONFIRMED.** Primary sources were unreachable: https://www.tomorrow.io/pricing/ → **HTTP 404**; the support article "Free API Plan Rate Limits" → **HTTP 403** via fetcher, and direct curl hit a Cloudflare interstitial.

What IS observable (OBSERVED, https://docs.tomorrow.io/reference/rate-limiting): *"According to your plan, you are limited to a certain amount of requests per hour and day"* — **no figures given**; 429 on exceed; headers `X-RateLimit-Limit-second|-hour|-day` exist but are *"currently available only for Enterprise accounts"* — **so a free user cannot even introspect their own quota.**

Figures circulating third-party (3 req/s, 25 req/hour, 500 req/day) come from a GitHub discussion and a Home Assistant forum thread, 2024–2025, not vendor docs — **UNCONFIRMED, deliberately not asserted.**

**Verdict:** avoid unless you need Tomorrow.io-specific parameters. Opaque limits + Cloudflare-walled docs + Enterprise-gated headers = poor fit for an autonomous agent.

## 22. Other genuinely-free weather options

**Bright Sky (DWD wrapper) — recommended for Germany.** *"a free, simple JSON API"* over DWD station observations + MOSMIX forecasts, `https://api.brightsky.dev/`, **no API key, MIT** (OBSERVED, https://github.com/jdemaeyer/brightsky). Endpoints verified from its own OpenAPI (v2.2.9): `/sources`, `/current_weather`, `/weather`, `/synop`, `/radar`, `/alerts`. Live probe succeeded. Self-host via `docker-compose up`. **Rate limits UNCONFIRMED.**

**DWD Open Data — recommended for raw model data.** Verbatim from `https://opendata.dwd.de/README.txt` (OBSERVED): *"Within its legal mandate, DWD offers weather and climate data free of charge… **Access is granted without registration.**"* DWD stores your IP for max 7 days. Live listing (OBSERVED): `/weather/` contains `alerts/`, `charts/`, `local_forecasts/` (MOSMIX), `maritime/`, `nwp/` (ICON), `radar/`, `satellite/`, `text_forecasts/`, plus `/climate_environment/`. Plain HTTP file server — trivially curl-able, but GRIB2/KMZ/BUFR payloads. INFERRED: Bright Sky for JSON, opendata.dwd.de for raw fields.

**Pirate Weather (Dark Sky replacement).** Free tier **10,000 API calls/month**; $2/month donation → 20,000 (OBSERVED, https://pirateweather.net/en/latest/). Dark Sky-styled JSON, *"a drop in replacement/alternative to the Dark Sky API"*. Sources GFS, HRRR, NBM (so US-strongest, INFERRED). **Licence UNCONFIRMED.**

**WeatherAPI.com — unusually permissive.** Free = **100K calls/month**, 3-day forecast, 1-day history, marine (1 day, no tides), limited alerts/AQI, Search/Astronomy/IP Lookup/Weather Maps. 95.5% uptime. **Both commercial and non-commercial use permitted ("Yes")** — unusual and valuable for a free tier (OBSERVED, https://www.weatherapi.com/pricing.aspx). Requests a link-back.

**Weatherbit — too restrictive.** Free = **50 requests/day**, 7-day daily forecast, current weather. **Non-commercial only, CC BY-NC 4.0.** Excludes hourly, history, maps (OBSERVED, https://www.weatherbit.io/pricing). INFERRED: not viable for production.

**wttr.in — the easiest possible CLI path.** *"console-oriented weather forecast service"*, ~100M queries/day, **Apache-2.0** (OBSERVED, https://github.com/chubin/wttr.in). `curl wttr.in/London`; **JSON via `?format=j1` or `j2`**; also plain text `?T`, HTML, PNG, Prometheus `p1`. Self-hostable (static Go binary). **Rate limits UNCONFIRMED**; upstream data is WorldWeatherOnline + internal sources, so provenance is indirect and there is no SLA.

**Météo-France — portal is migrating.** `donneespubliques.meteofrance.fr` is **being shut down**; migrate to `https://portail-api.meteofrance.fr` and `https://meteo.data.gouv.fr/` (OBSERVED). Registration, key requirements, and formats: **UNCONFIRMED**. INFERRED: Open-Meteo already redistributes ARPEGE/AROME, usually the easier path.

---

# PART III — RAW NWP MODEL DATA ON PUBLIC CLOUD

## 23. NOAA Open Data Dissemination (NODD)

**The "no cost, no auth" claim is real and explicit (OBSERVED, verbatim, https://www.noaa.gov/big-data-project-frequently-asked-questions):**
> *"The NOAA datasets made available through NODD are free for all users to access with no use restrictions and do not require any registration to access. The data is fully open for public access and can be downloaded with **no egress charges**."*

Partners: AWS, GCP, Azure.

**⚠ Nuance worth carrying:** the main https://www.noaa.gov/nodd page says something weaker — *"full and open data access at **no net cost to the taxpayer**"* (OBSERVED). That is about NOAA's budget, not your bill. **Cite the FAQ, not the landing page.**

**Access caveat (OBSERVED):** `https://www.noaa.gov/nodd/datasets` returns **HTTP 403** from CloudFront to plain curl. The canonical machine-readable roster is the AWS registry, not noaa.gov.

## 24. GFS — `noaa-gfs-bdp-pds`

| Property | Value | Tag |
|---|---|---|
| Bucket | `noaa-gfs-bdp-pds`, us-east-1 | OBSERVED |
| Requester Pays | **No** | OBSERVED (registry) |
| Auth | Anonymous — unsigned GET → 200 | OBSERVED (live) |
| Cadence | *"4 times a day, every 6 hours starting at midnight UTC"* | OBSERVED |
| Format | GRIB2 + `.idx`, plus NetCDF (`atmf*.nc`) | OBSERVED (live) |

**Forecast hours empirically derived, not assumed (OBSERVED):** listing all 209 `pgrb2.0p25` records for `gfs.20260726/00/atmos/` gives step sizes `[1, 3]` → **hourly f000–f120, then 3-hourly to f384** (16 days). Resolutions present in one cycle: `pgrb2.0p25`, `.0p50`, `.1p00`, plus secondary-parameter `pgrb2b.*`.

**Mirrors, both verified live and anonymous (OBSERVED):** GCP `gs://global-forecast-system` (returned `gfs.t00z.pgrb2.0p25.f000`, 509,300,477 bytes + `.idx`); Azure `https://noaagfs.blob.core.windows.net/gfs` (anonymous listing 200).

Also present: `noaa-gfs-warmstart-pds` and SNS topics `NewGFSObject` for event-driven pipelines. **Rate limits UNCONFIRMED** — no NOAA or AWS statement found. INFERRED: standard S3 service quotas apply, far above any agent's needs. Do not represent as "unlimited".

## 25. HRRR — `noaa-hrrr-bdp-pds` (+ Zarr)

Registry verbatim (OBSERVED): *"The HRRR is a NOAA real-time 3-km resolution, hourly updated, cloud-resolving, convection-allowing atmospheric model, initialized by 3km grids with 3km radar assimilation."* Requester Pays: No.

**Verified live rather than taken from docs (OBSERVED):**
- **Two domains:** `hrrr.20260726/conus/` and `.../alaska/`.
- Four product families: `wrfsfcf` (surface), `wrfprsf` (pressure), `wrfnatf` (native), **`wrfsubhf` (sub-hourly, 15-min)** — confirmed by 200 on `hrrr.t00z.wrfsubhf02.grib2`.
- Forecast length: `wrfsfcf48` → 200 (172 MB) at synoptic cycles; `hrrr.t01z.wrfsfcf18` → 200. Confirms **48 h extended at synoptic cycles, 18 h otherwise**.

**Zarr version:** `s3://hrrrzarr`, **us-west-1** (distinct from the GRIB bucket's us-east-1 — OBSERVED via `x-amz-bucket-region`). Registry: *"The HRRR ZARR formatted data was originally generated by the University of Utah under a grant provided by NOAA."* Utah docs describe chunking: *"Each variable is then encoded and compressed into 96 chunks (time,x,y)."* ⚠ The Utah docs page does **not** state the bucket name, region, or anonymous access — all three confirmed empirically. Treat hrrrzarr as community-maintained, not an operational NOAA guarantee (INFERRED).

## 26. Other NODD models — all live-verified 2026-07-26

| Model | Bucket | Today's data | Registry quote |
|---|---|---|---|
| NAM | `noaa-nam-pds` | ✅ | *"Four times daily (0000, 0600, 1200, and 1800 UTC)"* |
| RAP | `noaa-rap-pds` | ✅ | *"13 km and 50 vertical layers… integrated to 51 hours for the 03/09/15/21 UTC cycles"* |
| GEFS | `noaa-gefs-pds` | ✅ | *"21 separate forecasts, or ensemble members"*, 4×/day, 16 days |
| NBM | `noaa-nbm-grib2-pds` | ✅ | *"nationally consistent and skillful suite of calibrated forecast guidance"*; **hourly** |
| MRMS | `noaa-mrms-pds` | ✅ | *"delivered in real-time with a **2-minute update cycle**"*; `CONUS/`, `ALASKA/`, `CARIB/`, `ANC/` |
| NEXRAD L2/L3 | `unidata-nexrad-level2`/`-level3` | ✅ | ⚠ **bucket moved** |
| HAFS | `noaa-nws-hafs-pds` | ✅ | *"Event Driven"* |
| RTOFS | `noaa-nws-rtofs-pds` | ✅ | *"eddy resolving 1/12° global HYCOM"*, 8 days, daily |
| RRFS | `noaa-rrfs-pds` | ✅ | ⚠ **mid-transition** |

**Three findings that matter more than the table:**

1. **NEXRAD migration (OBSERVED, registry, verbatim):** *"The NEXRAD Level II archive data is moving to a new bucket: `unidata-nexrad-level2`… The old bucket and SNS topic are now deprecated and will no longer be available starting September 1, 2025."* **Any code referencing `noaa-nexrad-level2` is dead.**

2. **RRFS is mid-transition right now (OBSERVED, registry, verbatim):** *"Version 1 of the RRFS and REFS are scheduled to be implemented on **October 6th, 2026**… upon the start of the pre-implementation parallel phase, currently scheduled for **August 11th, 2026**, the RRFS/REFS *prototype* data feed will no longer be updated"* (per SCN 26-048). **Do not build on the RRFS prototype feed — it goes stale in ~2 weeks from this research date.**

3. **RRFS carries a different, stronger licence (OBSERVED):** *"NOAA data disseminated through NODD is made available under the Creative Commons 1.0 Universal Public Domain Dedication (CC0-1.0)… There are no restrictions on the use of the data."* Every other NODD model still carries the older prose licence (*"open to the public and can be used as desired… NOAA requests attribution"*). INFERRED: NODD is migrating to explicit CC0 dataset-by-dataset; both are permissive and commercial-safe, CC0 is cleaner legally.

**WW3 waves is not a separate bucket** — wave output lives *inside* the GFS bucket (OBSERVED, live): `gfs.20260726/00/wave/gridded/gfswave.t00z.arctic.9km.f000.grib2`.

## 27. NOMADS GRIB filter — powerful, but the limit is officially unpublished

**Works, and is genuinely powerful (OBSERVED, live test).** 2 m temperature over a 5°×5° box extracted from the 509 MB GFS file:
```
GET https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?file=gfs.t00z.pgrb2.0p25.f000
    &lev_2_m_above_ground=on&var_TMP=on&leftlon=-100&rightlon=-95&toplat=45&bottomlat=40
    &dir=%2Fgfs.20260726%2F00%2Fatmos
→ HTTP 200, 620 bytes, magic "GRIB"
```
Rolling window of ~10 days on disk (OBSERVED: `gfs.20260726` back to `gfs.20260717`).

**Rate limits — there is NO published numeric limit, and this is a *documented* absence, not a gap in searching.** The governing document is the NWS [Abusive User Policy](https://www.weather.gov/abusive-user-block) (OBSERVED, verbatim): *"Sometimes the NWS determines that a particular user is impacting our service delivery capability… we may find it necessary to block IP addresses or query types."* Guidance given instead of numbers: only request during cycle windows; *"Request only the data that you need"*; limit retries to *"1 minute intervals"*. Thresholds are described as dynamic and are deliberately unpublished. NOMADS root and `info.php?page=help` contain **no** rate-limit text (grepped, OBSERVED); `robots.txt` is 404.

**Recommendation (INFERRED):** treat NOMADS as a convenience for *ad-hoc small spatial subsets only*. NODD/S3 is the explicit scale-out answer; NOMADS is a shared operational box that will block you with no warning and no published line to stay under.

## 28. NWP Python tooling — the 2026 headline: the C-library problem is gone

**Biggest single finding (OBSERVED, https://github.com/ecmwf/eccodes-python):** *"From version 2.43.0, the ecCodes Python bindings on PyPi will depend on the PyPi package 'eccodeslib'… This package provides the binary ecCodes library"* — *"no external ecCodes binary library is required."* Verified live: `python -m cfgrib selfcheck` → `Found: ecCodes v2.48.0. Your system is ready.` **`pip install cfgrib` now Just Works, no compiler, no conda.**

**Undocumented bonus (OBSERVED):** the `eccodeslib` wheel also ships the full ecCodes **CLI toolchain** — `grib_ls`, `grib_get`, `grib_get_data`, `grib_dump`, `grib_filter`, `grib_copy`, `grib_set`, `grib_compare` — in `site-packages/eccodeslib/bin/`, verified working. They are **not on `$PATH`**; invoke by absolute path. INFERRED: this is a pip-installable wgrib2 substitute, and it does not appear to be widely known.

| Tool | Version (2026) | Licence | C toolchain? | CLI? |
|---|---|---|---|---|
| **Herbie** (`herbie-data`) | 2026.3.0 | **MIT** | No | **Yes** |
| cfgrib | 0.9.15.1 | Apache-2.0 | **No (changed)** | Yes |
| eccodes / eccodeslib | 2.47.0 / 2.48.0 | Apache-2.0 | **No (changed)** | Yes (off-PATH) |
| ecmwf-opendata | 0.3.31 | Apache-2.0 | No | UNCONFIRMED |
| pygrib | 2.1.8 | `MIT AND (Apache-2.0 OR BSD-2-Clause)` | Only off wheel matrix | No |
| **wgrib2** | 3.8.0 | **ambiguous — see below** | **Yes** | Yes |
| kerchunk | 0.2.10 | MIT | No | No |
| VirtualiZarr | 2.7.1 | Apache-2.0 | No | No |
| zarr | 3.2.1 | MIT | No | `[cli]` extra |

**⚠ wgrib2 licence is genuinely unclear — flag before shipping.** NOAA/CPC states: *"The source code modules for wgrib2 are either in the public domain or under the GNU licence depending on the authors of the various modules."* The NOAA-EMC/wgrib2 repo has **no LICENSE file at all** (GitHub API returns `license: null`, OBSERVED); conda-forge classifies it GPL-2.0-or-later; **no Homebrew formula** (`formulae.brew.sh/api/formula/wgrib2.json` → 404, OBSERVED); no PyPI wheel. Treat as GPL; avoid unless you need `-new_grid` regridding.

**Ranking for a Bash-shelling agent:**
1. **`curl` + `.idx` byte-ranges — zero install.** The default (see §29).
2. **`herbie` CLI (`uv tool install herbie-data`).** Resolves URLs *and* byte ranges across ~20 models (`cfs, ecmwf, gdps, gefs, gfs, hafs, hiresw, hrdps, href, hrrr, nam, nbm, nexrad, rap, rdps, rrfs, rtma, urma, usnavy`) over AWS/GCS/Azure/NOMADS, printing parseable stdout.
3. `grib_ls`/`grib_filter` from `eccodeslib` — arrives free with #2/#4.
4. `cfgrib` + `xarray` for actual array math.
5. Then `s5cmd --no-sign-request`, `aws s3api get-object --range`, `pygrib` (redundant), kerchunk/VirtualiZarr (needs an upfront manifest pass — wrong shape for one-shot agent tasks), wgrib2 last.

**Two Herbie gotchas (OBSERVED):** (a) product names are non-obvious — `--product 0p25` fails, you need `pgrb2.0p25`, and **Herbie's own docs example is wrong**; (b) it is **not side-effect-free** — first run writes `~/.config/herbie/config.toml` and creates `~/data/`.

## 29. The single most valuable technique — verified end-to-end

```bash
# 1. Pull the index (31 KB) instead of the file (509 MB)
curl -s https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.20260726/00/atmos/gfs.t00z.pgrb2.0p25.f000.idx \
  | grep ":TMP:2 m above ground:"
# -> 580:417970701:d=2026072600:TMP:2 m above ground:anl:

# 2. Byte-range GET just that record (end byte = next line's start - 1)
curl -s -r 417970701-418489787 \
  https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.20260726/00/atmos/gfs.t00z.pgrb2.0p25.f000 \
  -o t2m.grb2
# -> HTTP 206, 519,087 bytes. Magic: "GRIB". 0.1% of the full file.
```
**OBSERVED, live:** 519 KB instead of 509 MB — a **981× reduction**, using only `curl`, on a file with no authentication. The `.idx` format is `record:start_byte:date:VAR:level:fcst:`; the last record runs to EOF. This is the highest-leverage single trick in this entire document for a Bash-driven agent.

## 30. AI weather models — open weights ≠ free outputs

| Model | Weights free? | Weights licence | Commercial OK? | Free outputs? |
|---|---|---|---|---|
| **ECMWF AIFS** | UNCONFIRMED | — | — | **YES** — `s3://ecmwf-forecasts`, CC-BY-4.0, GRIB2 |
| GraphCast | Yes (`gs://dm_graphcast`) | **CC-BY-NC-SA-4.0** | **NO** | Yes, via NOAA |
| NeuralGCM | Yes | Apache-2.0 code / CC-BY-SA-4.0 weights | Yes | Climate output only |
| WeatherNext 2 | No | — | — | **Form-gated**; cost UNCONFIRMED |
| FourCastNet3 | Yes (HF, ungated) | Apache-2.0 | Yes | Yes, via NOAA |
| Pangu-Weather | Yes (GDrive/Baidu, ONNX) | **CC-BY-NC-SA-4.0** | **NO** | Yes, via NOAA |
| Aurora | Yes (HF, anon HTTP 200) | **MIT** | Yes (caveat) | Yes, via NOAA |

**Explicit non-commercial licences (OBSERVED, quoted):** GraphCast — *"The model weights are made available… under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)"* (code is Apache-2.0 — different licence for code vs weights). Pangu-Weather — *"The commercial use of these models is forbidden."* ⚠ NVIDIA's Earth2Studio (Apache-2.0) can *download* GraphCast and Pangu weights but states *"Licenses for these assets are owned by their providers"* — **the harness does not launder the NC terms.**

**Aurora is the most permissive (OBSERVED):** LICENSE.txt is MIT (Microsoft); HF `microsoft/aurora` reports `license: mit, gated: False`; anonymous HEAD on the checkpoint → HTTP 200, no token. Caveat: README says *"Please email AIWeatherClimate@microsoft.com if you are interested in using Aurora for commercial applications"* — INFERRED, MIT legally permits commercial use and this is a steer not a restriction, but flag the mismatch to legal.

**WeatherNext is NOT anonymously free (OBSERVED, https://developers.google.com/weathernext/guides/access-forecast):** *"If you are interested in accessing the datasets, fill out this WeatherNext Data Request form."* Data sits in BigQuery / Earth Engine / `gs://weathernext`. Whether querying is billed: **UNCONFIRMED** — INFERRED that BigQuery compute/egress bills the caller's project, so treat as not-free-at-scale.

### The headline: NOAA now runs AI models operationally, and the output is CC0

**Two NODD buckets, both anonymous, both verified live 2026-07-26.**

**A. NOAA AIGFS** — `s3://noaa-nws-graphcastgfs-pds` (OBSERVED, https://registry.opendata.aws/noaa-nws-graphcastgfs-pds/, verbatim):
> *"Effective on **December 17, 2025**, the NOAA/NWS National Centers for Environmental Prediction (NCEP) implemented three new models: the **Artificial Intelligence Global Forecast System (AIGFS)**, the Artificial Intelligence Global Ensemble Forecast System (AIGEFS), and the Hybrid Global Ensemble Forecast System (HGEFS)."*

Built on DeepMind's pre-trained GraphCast; 0.25°, 4×/day, GRIB2. **Licence OBSERVED: *"NOAA's GraphCast GFS products are released under CC0 license."*** Live probe: `aigfs.20260726/` present. **This is the practical route to commercially-usable GraphCast-quality forecasts despite the CC-BY-NC-SA weights — NOAA runs the model, NOAA's output is public domain.** Similarly `noaa-nws-fourcastnetgfs-pds`, also CC0.

**B. AIWP multi-model reforecasts** — `s3://noaa-oar-mlwp-data` (OBSERVED, https://registry.opendata.aws/aiwp/), NetCDF. Live prefixes: `AURO_v100_GFS/`, `AURO_v100_IFS/`, `FOUR_v100_GFS/`, `FOUR_v200_*`, `GRAP_v100_*`, `PANG_v100_*`, `Derived/`, `parquet/`. Aurora, FourCastNet, GraphCast and Pangu output side by side, no restrictions. ⚠ The bucket's own `README.txt` lists only 4 models and **omits Aurora — it is stale relative to actual contents.** Trust the listing.

---

# PART IV — INTEGRATION INTO CLAUDE CODE

## 31. The official MCP weather server — confirmed, and it's a tutorial

**OBSERVED:** https://modelcontextprotocol.io/quickstart/server is titled "Build an MCP server" and states *"we'll build a simple MCP weather server… exposes two tools: `get_alerts` and `get_forecast`"*, backed by `api.weather.gov`. Reference code: https://github.com/modelcontextprotocol/quickstart-resources — **1,148★**, push 2026-07-23, with Python/TypeScript/Go/Rust/Ruby variants.

**Critical context (OBSERVED):** the official reference-server repo https://github.com/modelcontextprotocol/servers (88,914★, push 2026-07-26) contains **only** `everything, fetch, filesystem, git, memory, sequentialthinking, time`. **There is no official weather, geo, or satellite MCP server.** INFERRED: every server below is third-party and unaudited, and the large tail of `mcp-weather` repos with 0★ created in 2025 are tutorial forks of this quickstart, not products.

## 32. Weather MCP servers — ranked inventory

All metadata OBSERVED via `gh api repos/{owner}/{repo}` on 2026-07-26.

| Rank | Repo | Backing source | Key | Licence | ★/forks | Last push | Install |
|---|---|---|---|---|---|---|---|
| **1** | [isdaniel/mcp_weather_server](https://github.com/isdaniel/mcp_weather_server) | **Open-Meteo** | **No** | Apache-2.0 | 55/35 | **2026-07-26** | `pip install mcp_weather_server`; Docker `dog830228/mcp_weather_server` |
| 2 | [ezh0v/weather-mcp-server](https://github.com/ezh0v/weather-mcp-server) | WeatherAPI.com | Yes | MIT | **246**/20 | 2026-03-01 | Go build or `docker run -e WEATHER_API_KEY=…` |
| 3 | [cyanheads/open-meteo-mcp-server](https://github.com/cyanheads/open-meteo-mcp-server) | Open-Meteo (+ERA5, GloFAS, CAMS, CMIP6) | **No** | Apache-2.0 | 2/1 | 2026-07-16 | `npx -y @cyanheads/open-meteo-mcp-server` |
| 4 | [TimLukaHorstmann/mcp-weather](https://github.com/TimLukaHorstmann/mcp-weather) | AccuWeather | Yes | MIT | 34/13 | 2025-09-08 | `npx -y @timlukahorstmann/mcp-weather` |
| 5 | [glaucia86/weather-mcp-server](https://github.com/glaucia86/weather-mcp-server) | OpenWeatherMap | Yes | MIT | 98/11 | 2025-10-28 | clone + npm/Docker (+Redis) |
| — | [adhikasp/mcp-weather](https://github.com/adhikasp/mcp-weather) | AccuWeather | Yes | Unlicense | 36/31 | **2025-01-01** — stale |
| — | [hideya/mcp-server-weather-js](https://github.com/hideya/mcp-server-weather-js) | NWS (quickstart port) | No | MIT | 14/10 | 2025-03-18 |
| — | [yestarz/mcp-server-weather](https://github.com/yestarz/mcp-server-weather) | unstated (Java) | ? | **none** | 26/6 | 2025-03-13 |

**Tool surfaces (OBSERVED from READMEs):**
- `isdaniel`: `get_weather_by_datetime_range`, `get_current_weather`, `get_air_quality`/`_details` (PM2.5, PM10, O3, NO2, CO, dust, AOD), `get_current_datetime`, `convert_time`, `get_timezone_info`. stdio + SSE + Streamable HTTP.
- `cyanheads`: 11 tools — `openmeteo_geocode`, `_get_forecast`, `_get_historical` (ERA5), `_get_marine`, `_get_air_quality` (CAMS), `_get_elevation`, `_get_ensemble`, `_get_flood` (GloFAS), `_get_climate` (CMIP6), + SQL analytics.
- `ezh0v`: **one tool only** — `current_weather(city)`. **Highest stars ≠ most capable.**

**Honest read (INFERRED):** the only weather servers simultaneously keyless, permissively licensed, and pushed in 2026 are `isdaniel/mcp_weather_server` (proven adoption: 35 forks, Docker badge) and `cyanheads/open-meteo-mcp-server` (far richer, but 2★ / ~2 months old, single maintainer, no adoption evidence). Everything else is key-gated, stale >9 months, or unlicensed — and **unlicensed = legally unusable in a commercial product.**

**Official MCP registry quality warning (OBSERVED, `registry.modelcontextprotocol.io/v0/servers?search=weather`):** dozens of weather entries, near-all vanity/hobby (`com.crosbynews/weather` = Crosby TX local weather; `dev.gtfo/mcp-killchain-stage1-weather` is literally a **security-research supply-chain-attack demo**). **Registry publication implies zero quality vetting.** One NWS-backed entry, `ai.smithery/smithery-ai-national-weather-service`, points at a repo returning **HTTP 404** — likely dead.

## 33. Satellite / EO / geospatial MCP servers

### Genuinely usable

| Repo | Wraps | Key | Licence | ★/forks | Last push |
|---|---|---|---|---|---|
| [ProgramComputer/NASA-MCP-server](https://github.com/ProgramComputer/NASA-MCP-server) | NASA Open APIs: **GIBS**, POWER, EONET, EPIC, CMR, APOD, NEO | `NASA_API_KEY` (free) | ISC | **92**/18 | 2026-07-04 |
| [mahdin75/geoserver-mcp](https://github.com/mahdin75/geoserver-mcp) | GeoServer REST (WMS/WFS) | GeoServer creds | MIT | **86**/24 | 2025-12-13 |
| [JordanGunn/gdal-mcp](https://github.com/JordanGunn/gdal-mcp) | GDAL-style raster/vector via Rasterio/PyProj | No | MIT | **72**/7 | 2026-05-25 |
| [datalayer/earthdata-mcp-server](https://github.com/datalayer/earthdata-mcp-server) | NASA Earthdata search + download + Jupyter | EDL | BSD-3 | 26/9 | 2026-03-19 |
| [nasa/earthdata-mcp](https://github.com/nasa/earthdata-mcp) | NASA **CMR** direct (official NASA org) | none stated | **NO LICENSE** | 19/11 | **2026-07-24** |
| [Wayfinder-Foundry/stac-mcp](https://github.com/Wayfinder-Foundry/stac-mcp) | Any STAC API (defaults to Planetary Computer) | No | MIT | 12/7 | 2026-07-22 |

Tools (OBSERVED): `gdal-mcp` → `raster_info/convert/reproject/stats/query`, `vector_info/convert/reproject/clip/buffer/simplify/query`, plus `justify_crs_selection`/`justify_resampling_method` reflection middleware. Install `uvx --from gdal-mcp gdal --transport stdio` or Docker.
`stac-mcp` → `search_collections`, `get_collection`, `search_items`, `get_item`, `get_queryables`, `get_aggregations`, `estimate_data_size` (odc.stac lazy-load sizing without download). Install `uvx --from git+https://github.com/wayfinder-foundry/stac-mcp stac-mcp` or `ghcr.io/wayfinder-foundry/stac-mcp:latest`.
`nasa/earthdata-mcp` → `get_collections`, `get_granules`, `get_keywords`, `get_services`, `get_variables`; remote Streamable HTTP + local `127.0.0.1:5001/mcp/v1`. **Caveat (OBSERVED): no LICENSE file on a NASA-org repo — blocks safe reuse.**

### High stars but risky
[jjsantos01/qgis_mcp](https://github.com/jjsantos01/qgis_mcp) — **1,035★/168 forks**, the most-adopted geospatial MCP by far. But: **NO LICENSE**, last push **2025-10-01** (~10 months stale), 16 open issues, README says *"only tested on [QGIS] 3.22"*, and it exposes **arbitrary Python execution inside QGIS**. High risk; avoid in anything commercial. (Directory sites quoting 573–846★ are stale caches; live value is 1,035.)

### OpenStreetMap / geocoding
`jagan-shanmugam/open-streetmap-mcp` (210★/46f, MIT, push 2025-07-12 — 12 mo stale) · `NERVsystems/osmmcp` (27★, MIT, Go, push 2026-03-20 — best-maintained OSM option) · `cyanheads/openstreetmap-mcp-server` (4★, Apache-2.0, push 2026-07-26, brand new).

### Toy / abandoned — stated plainly

| Repo | ★ | Push | Verdict |
|---|---|---|---|
| cameronking4/google-earth-engine-mcp | 13 | 2025-05-11 | Only GEE server with any traction; **14 months stale**, needs GCP service-account key |
| Dhenenjay/Axion-MCP | 4 | 2025-11-08 | Marketing copy > adoption |
| isaaccorley/planetary-computer-mcp | 4 | 2026-04-16 | Apache-2.0, `download_data`/`download_geometries`. Small but clean |
| IBM/chuk-mcp-stac | 0 | 2026-07-22 | IBM org, zero adoption |
| MCP4RemoteSensing/mcp4rs-open-earth | 0 | 2026-07-25 | **Created 2026-07-24 — two days old** |
| chrislyonsKY/geoflow-stac-mcp | 0 | 2026-03-07 | Rust/DuckDB, single-day commit history |
| sergekostenchuk/MCP-QGIS | 10/0f | 2026-06-08 | Newer QGIS alternative, unproven |
| **agronomist/sentinelhub-mcp** | **0** | 2025-10-02 | **The only Sentinel Hub MCP found. Dead.** |
| pipeworx-io/mcp-{nasa,nasa-cmr,nasa-eonet,nasa-power,gistemp,noaa,celestrak,meteors} | all **0** | 2026-06 | One-person MIT bulk-published server farm, registry-listed, no users |

**Gaps — OBSERVED (empty or near-empty search results):**
- **Copernicus / CDSE: no MCP server exists at all.** `gh search repos "mcp copernicus"` and `"copernicus data space mcp"` → **zero results.**
- **Landsat: zero dedicated MCP servers** (`"mcp landsat"` → 0 results); reachable only via NASA/STAC/PC servers.
- **GIBS: no dedicated server**; only inside `ProgramComputer/NASA-MCP-server`.
- **Naming-collision trap:** searching `"mcp sentinel"` is useless — ~20 unrelated repos named "MCP Sentinel" are **MCP security scanners**, not Sentinel satellite tools.

## 34. Open-source LLM-agent × satellite/weather projects (2025–2026)

| Project | What | Licence | ★/forks | Last push |
|---|---|---|---|---|
| [opengeos/GeoAgent](https://github.com/opengeos/GeoAgent) | Shared AI-agent layer exposing leafmap/geoai/geemap/STAC/NASA-Earthdata tools to LLMs (Strands Agents; OpenAI/**Anthropic**/Gemini/Bedrock/local). NASA OPERA search with bbox/date filters + QGIS plugin | MIT | **441**/83 | **2026-07-26** (created 2026-02-01) |
| [microsoft/Planetary-Explorer](https://github.com/microsoft/Planetary-Explorer) (redirect from `microsoft/Earth-Copilot`) | NL exploration of Earth-science data; MAF WorkflowBuilder + **MCP clients/servers**, STAC, GDAL/Rasterio, Fabric/Delta Lake; weather models incl. Aurora, NVIDIA Earth-2 FCN, MAI Weather. Descends from the NASA×Microsoft "Earth Copilot" announcement | MIT | **181**/49 | 2026-07-24 |
| [Chen-Yang-Liu/Change-Agent](https://github.com/Chen-Yang-Liu/Change-Agent) | Interactive change-detection + interpretation agent | MIT | 198/20 | 2025-07-27 |
| [HaonanGuo/Remote-Sensing-ChatGPT](https://github.com/HaonanGuo/Remote-Sensing-ChatGPT) | ChatGPT orchestrating RS vision models | **none** | 242/29 | **2024-03-27 — abandoned** |
| [mohammadhashemii/awesome-agentic-AI-for-ST](https://github.com/mohammadhashemii/awesome-agentic-AI-for-ST) | Curated list of spatio-temporal agentic AI (GeoCogent, ThinkGeo, GeoFlow, MapAgent, ShapefileGPT…) — best entry point to the literature | none | 33/3 | 2026-07-15 |
| [juaquicar/GeoAgents](https://github.com/juaquicar/GeoAgents) | Planner→verify→replan GIS agent framework | MIT | 3/0 | 2026-04-08 |

Supporting libraries the agents call: [opengeos/geoai](https://github.com/opengeos/geoai) **3,206★**, push 2026-07-25; [opengeos/leafmap](https://github.com/opengeos/leafmap) **3,736★**, push 2026-07-20 — both MIT. **INFERRED: the `opengeos` ecosystem is the healthiest place to build an EO agent today**; GeoAgent supplies the LLM layer and is under daily development.

**UNCONFIRMED:** *GeoLLM-Squad* ([arXiv:2501.16254](https://arxiv.org/abs/2501.16254), multi-agent geospatial copilot, 521 API functions) — **no public GitHub repo located.** Same for *RS-Agent* and the academic *GeoAgent* (hierarchical LLM multi-agent, QGIS case study). Treat as research, not usable code.

## 35. When does WebFetch substitute for an MCP server?

- **For keyless REST (NWS, Open-Meteo, MET Norway, NASA EONET/POWER/CMR): largely yes** (INFERRED). `api.weather.gov` is keyless public JSON with a documented two-hop pattern — exactly what the quickstart server hardcodes. The MCP server mainly adds typed args and saves a hop.
- **For key-gated APIs: no.** OpenWeatherMap/AccuWeather/WeatherAPI/Sentinel Hub/GEE need credential injection, which WebFetch has no mechanism for. **This is the real justification for those servers.**
- **For pixels: no.** WebFetch converts pages to markdown; it cannot open a COG, run `odc.stac`, compute NDVI, reproject a raster, or drive QGIS.
- **Caveat (OBSERVED):** WebFetch answers via a small fast model over converted markdown — it *summarizes* rather than returning raw structured JSON, which is **lossy for numeric weather series.** An MCP tool (or a Bash `curl | jq`) returning typed records is materially better when the numbers matter.

---

## 36. Cross-cutting traps to carry forward

1. **Two opposite S3 access models.** `usgs-landsat` = requester-pays, us-west-2, credentials mandatory. `noaa-goes*`, `noaa-himawari*`, `noaa-gfs/hrrr`, `sentinel-cogs`, `ecmwf-forecasts` = fully anonymous. A shared fetch layer needs both code paths. This also silently breaks Earth Search Landsat asset reads.
2. **Licence, not rate limit, is usually the binding constraint for a commercial product.** Open-Meteo free (10k/day) and Weatherbit (50/day) are **non-commercial only**; WeatherAPI.com (100K/mo), ECMWF Open Data (CC-BY-4.0), and all NOAA NODD data (CC0 or equivalent) permit commercial use. GraphCast and Pangu *weights* are CC-BY-NC-SA — but NOAA's AIGFS *output* is CC0.
3. **Truly zero-auth, zero-account sources:** NASA GIBS, Worldview Snapshots, CMR public search, NOAA GOES S3, NOAA STAR CDN (but see robots.txt), Himawari AWS, EUMETView WMS, EUMETSAT Data Store *search/browse*, LandsatLook STAC, Earth Search, Planetary Computer STAC (+ anonymously-obtainable SAS), all NODD NWP buckets, ECMWF Open Data, Open-Meteo, api.weather.gov, api.met.no, opendata.dwd.de, wttr.in. **Everything else needs a free account minimum.**
4. **Premises that needed correcting during this research (all OBSERVED):** `earthaccess` moved `nsidc/` → `earthaccess-dev/` (301); `eumdac` is on GitLab, not `github.com/eumetsat`; `eumartools` is on anaconda + a personal gitlab.com repo, not PyPI; `https://www.jma.go.jp/bosai/en_himawari/` is a 404; Planetary Computer Hub retired 2024-06-06 (not 2026); ECMWF's documented Azure mirror is not anonymously accessible; NEXRAD's AWS bucket moved and the old one died 2025-09-01; `pip install titiler` is dead; `nasa-nex-gddp-cmip6` is not a bucket (`nex-gddp-cmip6` is).
5. **Rate limits deliberately not invented here:** GIBS hard cap, CMR throttle thresholds, Worldview Snapshots limits, EDL API limits, NOAA S3/CDN limits, EUMETSAT throttling and Data Tailor quotas, USGS M2M limits, NOMADS numeric threshold, NWS numeric threshold, CDS/ADS queue limits, Bright Sky and wttr.in limits, Tomorrow.io free tier, Planetary Computer figures, GEE commercial prices, Sentinel Hub 2026 prices. Several have plausible-looking numbers circulating on secondary sites — in the EUMETSAT case two circulating sets disagree by ~2× — **none are asserted.**
6. **Two doc surfaces were down during this research and should be re-checked:** `eumetsatspace.atlassian.net` (site-level outage; it holds the Data Store Release Changelog with the current throttling numbers) and `www.noaa.gov/nodd` (403 to automated fetches).
