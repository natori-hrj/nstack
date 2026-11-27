---
name: interrogate
description: Independently challenge claims with executable or rigorous static evidence.
---

Use nstack_review only when the parent session is already read-only. Otherwise start a separate Codex CLI session with --sandbox read-only and the explicitly selected review model. Give the fresh reviewer the exact revision or diff, contract and minimal context. For each finding report location and evidence, affected contract, reproduction or test, actual and expected behavior, impact and root cause. Independently reproduce before remediation where feasible. Accept rigorous static security or architecture evidence with the reason execution is impractical. Group common root causes and distinguish defects from optional improvements and new requirements. Verify fixes against the original contract. After two failed fixes on the same premise, apply $principle-attack-the-premise before another attempt. Escalate unresolved architecture disagreements and stop when findings are resolved or explicitly handed off.
