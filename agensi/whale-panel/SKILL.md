---
name: whale-panel
description: Ask "what would Buffett, Graham or Lynch say about this stock?" and get three independent, deterministic verdicts scored from SEC filings — never an averaged score. Installs the open-source Whale Panel engine (Python, uv) from GitHub, pulls the company's EDGAR filings, scores them under versioned per-investor rubrics, and reports where the models agree and disagree. Greenblatt is available as a single-whale diagnosis. Use when a user asks for a Buffett-, Graham- or Lynch-style read on a ticker, a value-investing diagnosis, or a "whale panel" on a stock.
version: 1
---

# Whale Panel — install and run

Whale Panel is an MIT-licensed engine (https://github.com/philipbergman6-glitch/agents).
The design rule: **the engine computes, you narrate.** Every number you show the
user comes from the engine's JSON. You never compute, estimate, round beyond
presentation, or average the whales into one verdict.

This skill installs the engine once, then runs it. Tell the user up front:
"This clones a public GitHub repo and installs a Python package with uv. It
fetches SEC EDGAR filings and a delayed market quote (Cboe, falling back to
yfinance) over the network. Continue?" Stop if they say no.

Shell state does not survive between your commands. Every block below that
needs the install location re-reads it the same way:

```bash
WHALE_HOME="${WHALE_HOME:-$HOME/whale-panel}"
```

## 1. Prerequisites (check, don't assume)

Run each and report what is missing. Install nothing silently.

```bash
git --version
uv --version          # https://docs.astral.sh/uv/getting-started/installation/
python3 --version     # uv fetches 3.11+ itself if the system lacks it
```

If `uv` is missing, show the user the one-line installer from the uv docs and
ask them to run it, or ask permission to run it. Do not pip-install the engine;
it is a uv-managed package with a lockfile.

## 2. Install (first run only)

```bash
WHALE_HOME="${WHALE_HOME:-$HOME/whale-panel}"
if [ ! -d "$WHALE_HOME/.git" ]; then
  git clone --depth 1 https://github.com/philipbergman6-glitch/agents "$WHALE_HOME"
fi
cd "$WHALE_HOME/whale_engine" && uv sync --frozen
uv run whale --help | head -5
```

If `uv sync` fails, print the error verbatim and stop. Do not patch the repo.
The clone ships pinned snapshots under `snapshots/`; they are months old and
exist for reproducibility, not as a substitute for a fresh fetch.

## 3. EDGAR identity (required by the SEC, not by us)

The SEC requires a name and email on every EDGAR request. If `EDGAR_IDENTITY`
is not already set in the environment, **ask the user** for their name and email
and pass it inline on the fetch command in step 4, as
`EDGAR_IDENTITY="Jane Doe jane@example.com"`. Never invent one, never reuse one
from another user, never write it to a file unless the user asks you to.

## 4. Run the panel

```bash
WHALE_HOME="${WHALE_HOME:-$HOME/whale-panel}"
cd "$WHALE_HOME/whale_engine"
ls "snapshots/TICKER-$(date +%F).json" 2>/dev/null \
  || EDGAR_IDENTITY="Name email@example.com" uv run whale fetch TICKER   # network
uv run whale panel TICKER                                                 # offline, newest snapshot
```

`whale panel` prints JSON. Keep it. Its `provenance.snapshot` is the file every
diagnose below must read, so all figures describe the same filing date:

```bash
uv run whale diagnose TICKER --whale buffett --snapshot <provenance.snapshot>   # also: graham, lynch, greenblatt
```

If `fetch` fails, report the error and the newest snapshot date present in
`snapshots/` for that ticker, and proceed only if the user accepts a stale
snapshot. Pass that file explicitly as `--snapshot` to both `panel` and
`diagnose`. Never mix snapshot dates across whales.

## 5. Report (what you may and may not say)

The panel JSON and the diagnose JSON are your only sources of figures. Print,
in this order:

1. **Panel** — one line per whale from `whales.<name>`, in JSON order:
   `**Buffett** — <signal>, <confidence>/100 confidence, <score.total>/<score.max_possible>: <one key driver quoted from that whale's diagnose details>`.
   A whale with `walked_away: true` is reported as
   `**Lynch** — walks away: <reason field, verbatim>`. That is a position, not
   an error; the panel proceeds over the whales that scored and says so.
2. The engine's `engine_count` string, verbatim, on its own line.
3. If `unanimity_suspect` is true, this sentence, with the distinct
   `data_quality_warnings[].code` values deduplicated in JSON order:
   `Unanimity flag: the engine marks this agreement suspect because the snapshot carries data-quality warnings (<codes>) — every rubric that scored read the same flagged input, and agreement on a flagged input is not independent confirmation; see the caveats.`
4. **Where the models diverge** — attribute every difference to the *model*
   (DCF vs Graham Number vs PEG), quoting `details` strings from the diagnose
   JSON. Name instruments, never counts of whales.
5. **Caveats** — `provenance.snapshot` and `provenance.snapshot_fetched_at`;
   one plain-English line per distinct warning code with the figure the engine
   attached to it (for example `lag_days`); then this closing line verbatim:
   *These are mechanical rubrics plus narration, not investment advice.*

Hard rules:

- No "2 of 3", no "on balance", no "the panel leans". The only tally is the
  engine's count line.
- Dollar figures may be rounded to human scale ($14,740,350,000 → $14.74B).
  Ratios, scores and percentages stay exactly as printed.
- If `panel` or `diagnose` exits non-zero, print its stderr and stop. No partial
  panel. (A failed `fetch` is handled in step 4.)

## 6. Going further

Users who run Claude Code can open a session in `$WHALE_HOME`: the repo ships
`/buffett`, `/graham`, `/lynch`, `/greenblatt`, `/panel` and `/portfolio`
skills with full persona narration and a narration-contract test suite. Same
engine; the repo adds the voices.

Source, rubrics, tests and design records: https://github.com/philipbergman6-glitch/agents
