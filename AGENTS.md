Development repo for the Buffett company-diagnosis agent (deterministic scoring engine + Claude Code subagent). The engine is a uv-managed Python package in `buffett/` — run its CLI from that directory (`uv run buffett fetch|diagnose TICKER`; fetch needs `EDGAR_IDENTITY` set). Tests: `cd buffett && uv run pytest`.

To diagnose a company, delegate to the `buffett` subagent (`.claude/agents/buffett.md`) or the `/buffett TICKER` skill — never compute or estimate financial numbers yourself; every number must come from the engine.
