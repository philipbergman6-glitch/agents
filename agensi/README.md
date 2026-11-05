# Marketplace packaging

`whale-panel/` is the self-contained skill to be published, free, on
Agensi.io. It is deliberately a thin pointer: it clones this repo, runs
`uv sync --frozen`, and drives the `whale` CLI. The rubrics, personas and
tests live only here; the marketplace copy carries the install steps plus a
copy of the panel's report rules, which the checklist below re-syncs.

The clone tracks `main` at install time and is never updated, so a CLI rename
breaks installed copies silently. Pin `git clone` to a tag once one exists.

Republish checklist (no engine change is needed): diff the report rules in
`whale-panel/SKILL.md` against `.claude/skills/panel/SKILL.md`; re-run the
cold install (fresh clone, `uv sync --frozen`, `uv run whale panel KO`
offline); bump `version` in the frontmatter; submit the folder.
