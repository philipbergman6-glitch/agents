---
name: graham
description: Diagnose a company Graham-style — /graham TICKER. Delegates to the graham subagent, which runs the deterministic scoring engine and narrates the result.
---

Delegate to the `graham` subagent via the Agent tool. Pass the ticker and any user preferences (e.g. "fresh data", a specific snapshot file) through in the prompt:

> Diagnose $ARGUMENTS.

Relay the subagent's diagnosis to the user unchanged. Do not add your own numbers or commentary.
