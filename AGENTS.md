Development repo for the Buffett company-diagnosis agent (deterministic scoring engine + Claude Code subagent). The engine is a uv-managed Python package in `buffett/` — run its CLI from that directory (`uv run buffett fetch|diagnose TICKER`; fetch needs `EDGAR_IDENTITY` set). Tests: `cd buffett && uv run pytest`.

Internally the package is `whale_engine`: shared fetch/snapshot/CLI plus per-investor rubrics in `src/whale_engine/scorers/` (snapshots are whale-agnostic raw data — fetch once, any scorer diagnoses from the same file). The generic CLI is `uv run whale diagnose TICKER --whale NAME`; `uv run buffett …` is the Buffett-pinned equivalent and its behavior is frozen.

To diagnose a company, delegate to the `buffett` subagent (`.claude/agents/buffett.md`) or the `/buffett TICKER` skill — never compute or estimate financial numbers yourself; every number must come from the engine.
