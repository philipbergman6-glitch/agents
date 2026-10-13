---
name: greenblatt
description: Diagnose a company Greenblatt magic-formula-style — /greenblatt TICKER. Delegates to the greenblatt subagent, which runs the deterministic scoring engine and narrates the result.
---

Delegate to the `greenblatt` subagent via the Agent tool. Pass the ticker and any user preferences (e.g. "fresh data", a specific snapshot file) through in the prompt:

> Diagnose $ARGUMENTS.

Relay the subagent's diagnosis to the user unchanged. Do not add your own numbers or commentary.
