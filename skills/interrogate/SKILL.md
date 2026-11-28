---
name: interrogate
description: Independently verify consequential changes and close findings with evidence.
---

Use the active adapter to launch the configured independent reviewer in an enforced read-only session. Give the reviewer the exact candidate revision or diff, behavioral contract and minimal context. If independent review is required and the route is unavailable, report the blocker.

Record location, evidence, actual and expected behavior, impact and suspected root cause. Reproduce defects before remediation where feasible. Explain when static evidence is sufficient. Distinguish acceptance violations from optional improvements and scope changes. Group findings by root cause and rerun affected checks on the revised candidate.

Follow the project review budget, defaulting to at most two fix-and-recheck rounds after initial review. After two failures at the same gate on the same premise, stop patching, test the premise directly and use $architect. Escalate scope or contract changes, and hand off unresolved findings with exact revision and evidence.

For an operator-authorized one-invocation workflow, use the active adapter's documented host entrypoint when native delegation cannot enforce the review permissions. Treat authentication, sandbox, and model verification failures as delivery blockers.
