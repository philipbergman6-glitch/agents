# Marketplace packaging

`whale-panel/` is the self-contained installer skill published (free) on
Agensi.io. It is deliberately a thin pointer: it clones this repo, runs `uv
sync`, and drives the `whale` CLI. The rubrics, personas and tests live only
here, so the marketplace copy can never drift from the engine.

Publishing checklist: bump nothing in the engine; re-read the SKILL.md against
`.claude/skills/panel/SKILL.md` for changed command names; submit the folder.
