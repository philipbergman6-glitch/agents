# agents — investor "whale" agents built on Claude Code

## The big picture

This repo answers one question: **"What would a famous investor say about this stock?"** — without letting an AI make up numbers.

It does that by splitting the job in two:

1. **A calculator (the engine).** Plain Python code that downloads a company's real
   financial filings from the SEC, saves them to a file, and scores the company
   using each investor's rules. Same input → same score, every time. No AI involved.
2. **A narrator (the agent).** Claude reads the engine's output and explains the
   verdict in that investor's voice. It is only allowed to describe numbers the
   engine produced — never to compute or estimate its own.

The investors are nicknamed **whales** (big famous investors). Three exist today:

| Whale | Style, in one line | How it judges |
|---|---|---|
| **Buffett** | Wonderful business at a fair price | Moats, owner earnings, a conservative DCF |
| **Graham** | Cheap and safe, by the numbers | Strict value and safety tests |
| **Lynch** | Growth at a reasonable price | Classifies the company, then checks PEG |

You can ask one whale, or convene all three as a **panel** that shows where they
agree and disagree — deliberately without merging them into a single verdict,
because three different philosophies shouldn't be averaged.

## How to use it

All commands run from `whale_engine/`. Fetching needs `EDGAR_IDENTITY` set
(your name + email — the SEC requires it on downloads).

**In Claude Code (the normal way):**

- `/buffett AAPL` — one whale's diagnosis, narrated in its voice
- `/graham AAPL`, `/lynch AAPL` — same, other whales
- `/panel AAPL` — all three in parallel, plus an agreement/disagreement summary

**Directly on the command line (numbers only, no narration):**

```bash
cd whale_engine
uv run whale fetch AAPL              # download filings → snapshots/AAPL-<date>.json
uv run whale diagnose AAPL --whale buffett   # score from the snapshot
uv run buffett fetch|diagnose AAPL   # shortcut pinned to Buffett
uv run pytest                        # run the engine's tests
```

## What lives where

- `whale_engine/` — the Python engine (a `uv`-managed package)
  - `src/whale_engine/scorers/` — one file of scoring rules per whale
  - `snapshots/` — downloaded filing data, one JSON per ticker per day.
    Snapshots are whale-agnostic raw data: fetch once, and any whale can
    score from the same file (which also makes every diagnosis reproducible).
  - `tests/` — engine tests
- `.claude/agents/` — the personas: how each whale talks and what it may/may not do
- `.claude/skills/` — the `/buffett`, `/graham`, `/lynch`, `/panel` commands
- `portfolios/` — real holdings data (e.g. Berkshire's 13F) for context

## Provenance

The per-whale scoring rubrics (which ratios, which thresholds, how many
points) are adapted from the analyst heuristics in the open-source
[ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) project (MIT).
Everything else — the deterministic engine, hard-fail missing-data semantics,
versioned rubrics, golden-file tests, and the panel orchestration — is original
to this repo. Comments that mention "the reference" compare against those
upstream heuristics.

## Ground rules

- **The engine computes; Claude narrates.** No number in any diagnosis comes
  from the AI. If data is missing, the engine hard-fails and the whale
  "walks away" — it never guesses.
- **Scoring rules are versioned.** Every diagnosis records its `rubric_version`.
  Changing Buffett's rules requires an owner-signed review — never a silent edit.
- **The panel never averages.** It reports each whale's verdict and attributes
  disagreements to their differing models.

