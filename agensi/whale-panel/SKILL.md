---
name: whale-panel
description: Ask "what would Buffett, Graham or Lynch say about this stock?" and get three independent, deterministic verdicts from SEC filings — never an averaged score. Installs the open-source Whale Panel engine (Python, uv) from GitHub, pulls the company's EDGAR filings, scores them under versioned per-investor rubrics, and reports where the models agree and disagree. Use when a user asks for a Buffett/Graham/Lynch/Greenblatt-style read on a ticker, a value-investing diagnosis, or a "whale panel" on a stock.
---

# Whale Panel — installer skill

Whale Panel is an MIT-licensed engine (https://github.com/philipbergman6-glitch/agents).
The design rule: **the engine computes, you narrate.** Every number you show the
user comes from the engine's JSON. You never compute, estimate, round beyond
presentation, or average the whales into one verdict.

This skill installs the engine once, then runs it. Tell the user up front:
"This clones a public GitHub repo and installs a Python package with uv. It
fetches SEC EDGAR filings over the network. Continue?" Stop if they say no.

## 1. Prerequisites (check, don't assume)

Run each and report what is missing. Install nothing silently.

```bash
git --version
uv --version          # https://docs.astral.sh/uv/getting-started/installation/
python3 --version     # uv will fetch 3.11+ itself if needed
```

If `uv` is missing, show the user the one-line installer from the uv docs and
ask them to run it (or ask permission to run it). Do not pip-install the engine;
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

## 3. EDGAR identity (required by the SEC, not by us)

The SEC requires a name and email on every EDGAR request. Check:

```bash
echo "${EDGAR_IDENTITY:-unset}"
```

If unset, **ask the user** for their name and email and export it for this
session only: `export EDGAR_IDENTITY="Jane Doe jane@example.com"`. Never invent
one, never reuse one from another user, never write it to a file without asking.

## 4. Run the panel

```bash
cd "$WHALE_HOME/whale_engine"
uv run whale fetch TICKER                      # network: EDGAR filings + market cap -> snapshots/TICKER-<date>.json
uv run whale panel TICKER                      # offline: all three whales over that snapshot
```

`whale panel` prints JSON. Keep it; it is your only source of figures. Then, for
each whale the user cares about, the single-whale detail:

```bash
uv run whale diagnose TICKER --whale buffett   # also: graham, lynch, greenblatt
```

If `fetch` fails, report the error and the newest snapshot date present in
`snapshots/`, and proceed only if the user accepts a stale snapshot. Never mix
snapshot dates across whales.

## 5. Report (what you may and may not say)

Print, in this order:

1. **Panel** — one line per whale from `whales.<name>`:
   `**Buffett** — <signal>, <confidence>/100 confidence, <score.total>/<score.max_possible>`.
   A whale with `walked_away: true` is reported as `walks away: <reason>`. That
   is a position, not an error.
2. The engine's `engine_count` string, verbatim, on its own line.
3. If `unanimity_suspect` is true: say the engine marks the agreement suspect
   because every rubric read the same flagged input, and list the
   `data_quality_warnings[].code` values.
4. **Where the models diverge** — attribute every difference to the *model*
   (DCF vs Graham Number vs PEG), quoting the `details` strings from the
   diagnose JSON. Name instruments, not counts.
5. **Caveats** — snapshot path and `snapshot_fetched_at` from `provenance`,
   each data-quality warning in plain English, and this closing line verbatim:
   *These are mechanical rubrics plus narration, not investment advice.*

Hard rules:

- No "2 of 3", no "on balance", no "the panel leans". The only tally is the
  engine's count line.
- Dollar figures may be rounded to human scale ($14,740,350,000 → $14.74B).
  Ratios, scores, percentages stay exactly as printed.
- If the engine exits non-zero, print its stderr and stop. No partial panel.

## 6. Going further

Users who run Claude Code can `cd "$WHALE_HOME"` and open a session there: the
repo ships `/buffett`, `/graham`, `/lynch`, `/greenblatt`, `/panel` and
`/portfolio` skills with full persona narration and a narration-contract test
suite. Everything above is the same engine; the repo adds the voices.

Source, rubrics, tests and design records: https://github.com/philipbergman6-glitch/agents
