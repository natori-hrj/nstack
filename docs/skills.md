# Skill reference

[日本語](skills.ja.md) · [Quick start](../README.md)

## Choose a skill

Start with `$natori-mode` when you have an outcome but need help choosing a workflow. Codex reads the request, repository instructions, worktree state, and existing checks, then defines an acceptance check and reads only the applicable playbook. Bug fixes, features, and refactors have dedicated playbooks. Investigation stays read-only, and design uncertainty routes to `$architect`. The router can draw on narrower skills or principles as needed. This routing happens within an explicitly started session. The distributed skills have implicit invocation disabled.

For a specific job, invoke its skill directly.

- **Prove or fix a defect** — use `$tdd` to demonstrate a failing behavior through the public interface, `$correct` to repair a disproven claim, or `$interrogate` to independently review a claim or patch.
- **Understand a change** — use `$blast-radius` to map affected contracts, `$architect` to settle a design decision, or `$reflect` to retain a recurring lesson.
- **Run work in parallel** — use `$swarm` for different independent tasks with separate owners. Use `$arena` to compare alternative patches for the same task under identical criteria. In an arena the operator chooses the patch.
- **Prepare delivery** — use `$babysit` to track the current head of an existing PR until merge-ready or blocked. Use `$autopilot-stack` to prepare multiple candidates in dependency order. It uses the babysit playbook for existing PRs and stops at handoff.
- **Manage a session** — use `$setup-nstack` to check your installation, `$pause-safely` to stop and record state, and `$session-pickup` to recover it.

## Workflow skills

Each example is a prompt to enter in Codex. The last column describes the handoff or completion point.

| Skill | When to use it and example | Expected result and stopping condition |
|---|---|---|
| [natori-mode](../skills/natori-mode/SKILL.md) | General engineering task. `$natori-mode Fix duplicate imports on retry and verify the result` | An outcome, an acceptance check, and evidence from the chosen workflow. Finish after recording evidence and limitations. |
| [setup-nstack](../skills/setup-nstack/SKILL.md) | First run or routing check. `$setup-nstack Check skill discovery and confirm my model assignments` | Discovery, model, effort, and concurrency check. Record requested models separately from provider-confirmed evidence. Ask for an explicit choice if a route is unavailable. |
| [architect](../skills/architect/SKILL.md) | Consequential design choice. `$architect Should import validation move to the CLI boundary?` | Record the selected design, tradeoffs, and unresolved decisions. Escalate disagreement that changes contract or scope. |
| [swarm](../skills/swarm/SKILL.md) | Independent tasks. `$swarm Fix the CSV parser and independently update the logging guide` | Record dependencies, overlap, owners, bases, diffs, tests, and blockers. Serialize only optional parallelism when the serial route meets all requirements; stop on missing mandatory capabilities. The coordinating session applies repository delivery rules. |
| [arena](../skills/arena/SKILL.md) | Competing approaches to one task. `$arena Compare two ways to parse quoted fields against the same fixtures` | Compare behavior, patch size, and maintenance cost within the agreed budget. Hand patch selection and worktree cleanup to the operator. |
| [interrogate](../skills/interrogate/SKILL.md) | Independent evidence-based review. `$interrogate Review this diff against the import retry contract` | Report location, evidence, contract, reproduction where feasible, actual and expected behavior, impact, and root cause. Group shared causes and separate optional changes. Explain static evidence when execution is impractical. After two failed fixes sharing a premise, test that premise. Stop when resolved or explicitly handed off. |
| [tdd](../skills/tdd/SKILL.md) | Meaningful behavioral regression. `$tdd Prove that importing the same file twice produces one record` | Demonstrate expected failure, apply the smallest root-cause fix, and rerun through the normal entry point. Run mandatory checks on the final publication candidate. |
| [blast-radius](../skills/blast-radius/SKILL.md) | Cross-boundary change. `$blast-radius Identify who depends on this persisted import format` | Report direct and indirect effects, old data, side effects, rollback paths, and the smallest checks covering them. Distinguish observations from hypotheses. |
| [correct](../skills/correct/SKILL.md) | Claim or implementation disproven. `$correct The example says retries are idempotent, but this fixture creates duplicates` | Reproduce independently when feasible, correct the root cause, and report the rerun. Test the shared premise after two failed fixes. |
| [reflect](../skills/reflect/SKILL.md) | Recurring failure or lesson. `$reflect Capture the lesson from repeated import boundary regressions` | Capture a test, type, invariant, or simplification. For a procedural lesson, update the relevant instruction briefly where authorized. |
| [babysit](../skills/babysit/SKILL.md) | Existing PR. `$babysit Check PR 42 for merge readiness and report blockers` | Track the exact head, CI, conflicts, and review. Revalidate changed heads and retry only known transient failures within budget. Stop when merge-ready or concretely blocked. |
| [autopilot-stack](../skills/autopilot-stack/SKILL.md) | Dependent PR candidates. `$autopilot-stack Prepare parser changes before the CLI changes that depend on them` | Map prerequisites and owners, review the final patches, run mandatory gates on the exact candidates, and hand off in dependency order. |
| [session-pickup](../skills/session-pickup/SKILL.md) | Resume interrupted work. `$session-pickup Continue the import fix using the recorded session ID and handoff` | Resume by ID or use the latest handoff. Verify the base, worktree, owners, and last check. Repeat stale checks and continue. |
| [pause-safely](../skills/pause-safely/SKILL.md) | Suspend work. `$pause-safely Stop the writers and leave a handoff for tomorrow` | Stop starting work, interrupt active sessions, confirm writers stopped, and record IDs, revisions, dirty files, checks, blockers, and next action. Preserve worktrees and edits. |

The router’s seven playbooks are [bug fix](../skills/natori-mode/playbooks/bug-fix.md), [feature](../skills/natori-mode/playbooks/feature.md), [refactoring](../skills/natori-mode/playbooks/refactoring.md), [babysit](../skills/natori-mode/playbooks/babysit.md), [autopilot-stack](../skills/natori-mode/playbooks/autopilot-stack.md), [session pickup](../skills/natori-mode/playbooks/session-pickup.md), and [pause safely](../skills/natori-mode/playbooks/pause-safely.md).

## Engineering principles

These are decision aids. Apply the relevant principle during a task and use the resulting decision or check in the workflow handoff.

| Skill | When to use it | Result or completion check |
|---|---|---|
| [principle-laziness-protocol](../skills/principle-laziness-protocol/SKILL.md) | A diff is growing or a decision repeats. | One source of truth and the smallest sufficient change. |
| [principle-foundational-thinking](../skills/principle-foundational-thinking/SKILL.md) | Before choosing types, data shapes, or shared state. | Shapes fit access patterns, mutable state is isolated where needed, and useful scaffolding comes first. |
| [principle-attack-the-premise](../skills/principle-attack-the-premise/SKILL.md) | Two fixes sharing an assumption fail the same gate. | State the premise and test it directly before making another fix. |
| [principle-subtract-before-you-add](../skills/principle-subtract-before-you-add/SKILL.md) | Before adding or restructuring code. | Remove dead or redundant complexity before building. |
| [principle-boundary-discipline](../skills/principle-boundary-discipline/SKILL.md) | Wiring validation, failures, or adapters. | Parse and validate at crossing points. Keep internal logic pure and typed. |
| [principle-type-system-discipline](../skills/principle-type-system-discipline/SKILL.md) | Designing typed APIs or domain models. | Represent legal states, distinguish semantic primitives, exhaust variants, and derive types from authoritative schemas. |
| [principle-prove-it-works](../skills/principle-prove-it-works/SKILL.md) | Before declaring work complete. | Direct evidence from the actual artifact, scripted when possible. |
| [principle-fix-root-causes](../skills/principle-fix-root-causes/SKILL.md) | Debugging recurring or unclear symptoms. | Reproduce and fix the first incorrect decision or unhandled legitimate state. Check other instances of the fault. |
| [principle-sequence-verifiable-units](../skills/principle-sequence-verifiable-units/SKILL.md) | Migrations, sweeps, or stacked changes. | Each small unit has a baseline, a change, and a successful check before advancing. |
| [principle-test-behavior-not-implementation](../skills/principle-test-behavior-not-implementation/SKILL.md) | Writing or evaluating tests. | Tests fail when observable behavior breaks and pass when only internals change. |
| [principle-guard-the-context-window](../skills/principle-guard-the-context-window/SKILL.md) | Large reads, tool outputs, or fan-out planning. | Set file and turn limits per phase. Keep summaries in the main thread when delegating bulk work. |
| [principle-encode-lessons-in-structure](../skills/principle-encode-lessons-in-structure/SKILL.md) | An instruction or correction keeps recurring. | Encode an enforceable rule once. For a judgment call, highlight the instruction and give an example. |

## Models, isolation, and publication

The [example TOMLs](../examples/agents/) use `nstack_implement` with Sol, `nstack_security` with Sol for authorized defensive work, and `nstack_review` with Astra. Configure model and reasoning effort in the installed TOMLs, and subagent concurrency through Codex’s `[agents]` settings. Independently launched CLI sessions need an operator-set limit. Daybreak requires approved access and the appropriate program selection. Stop if a mandatory model is unavailable. Use a read-only parent for the review agent or launch a separate read-only session. Consult the [Codex adapter](codex.md) for access and sandbox details.

Give each concurrent writer a separate branch, worktree, and Codex session. Worktree paths alone provide no write restrictions. Check the effective sandbox and leave sibling worktrees out of the writable scope. Apply repository authorization for routine GitHub delivery. Release publication and merging require explicit operator authorization. Cursor Cloud, Bugbot, and Cursor Automations are outside the adapter’s scope.

## Other installation options

For project scope, place skills under `.agents/skills/`, agent TOMLs under `.codex/agents/`, and both MIT notices at the project root under prefixed names.

For native plugin installation, register the checkout in a local marketplace. If the checkout itself is the marketplace root, use this `.agents/plugins/marketplace.json`.

```json
{
  "name": "nstack-local",
  "plugins": [{
    "name": "nstack",
    "source": {"source": "local", "path": "./"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity"
  }]
}
```

```sh
codex plugin marketplace add /absolute/path/to/local-marketplace
codex plugin add nstack@nstack-local
```

The plugin supplies namespaced skills. Pick `$nstack:natori-mode` or `$nstack:setup-nstack` in the skill picker. Install the custom agent TOMLs separately using the [quick-start instructions](../README.md).
