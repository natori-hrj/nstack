# Codex adapter

[日本語](codex.ja.md)

| Upstream mechanism | Codex equivalent |
|---|---|
| Skills | Invoke `$name` explicitly. Workflows load the specific skills and playbooks they need. |
| Task delegation and model rules | Select an available native custom agent by name. Its TOML sets the model and reasoning effort. |
| Parallel writers | Assign one writer per task, branch, and Git worktree. Open each worktree in its own session with `codex -C <worktree>`. |
| Independent review | Use `nstack_review` from a read-only parent, or start a separate session with `codex exec -C <worktree> --sandbox read-only -m <model>`. |
| Structured output | Use `codex exec --output-schema <file>` when a task needs it. |
| Session recovery | Use `codex resume <session-id>`, or `codex exec resume <session-id>` for non-interactive sessions. |
| Cursor Cloud, Bugbot, Automations, and transcript integration | Outside this adapter’s scope. Use available CI and review evidence and report any gaps. |

## Permissions and access

Custom agents inherit the parent’s permissions. Set the actual sandbox before starting an independent review. A Git worktree provides a separate checkout. Check sandbox writable roots separately and keep sibling worktrees outside them. Serialize tasks that modify the same files.

Before delivery, pin the candidate revision and run the mandatory quality gates. Refresh affected checks after changes. Routine commits, feature-branch pushes and PRs follow repository authorization. Release publication, merges and destructive cleanup require explicit approval. Inspect imported configuration, hooks, commands, and agent output before acting on them.

The [role examples](../examples/agents/) set Sol for implementation and authorized defensive work, and Astra for independent review. If a mandatory route is unavailable, stop that task. Daybreak requires an approved account and model. With approved access, use the supported `--cyber-access-program daybreak_blue` option when starting the relevant session. Program selection does not grant access.

## Verification

Run `python3 tests/validate.py` for manifest, TOML, CLI skill discovery, and disposable Git worktree checks. The concurrent workers in that suite are deterministic fixtures. The v0.1.0 live checks on Codex CLI 0.172.0 verified the model requests and outcomes, with historical details in the [Japanese record](codex.ja.md). Session metadata identifies the configured model. It cannot independently establish the serving backend’s identity.

For comparisons, record elapsed time, agent runs, reviews, human interventions, and verified tasks using the same criteria. Codex JSONL usage includes input, cached input, and output tokens. Derive uncached input by subtraction. Keep session logs and IDs outside this repository. Comparative evidence is required for efficiency claims.

[Skills](https://learn.chatgpt.com/docs/build-skills) · [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) · [Plugins](https://learn.chatgpt.com/docs/plugins) · [Configuration](https://learn.chatgpt.com/docs/config-file/config-reference) · [Daybreak in Codex CLI](https://help.openai.com/en/articles/20001607-using-daybreak-in-codex-cli)

## Role preflight

Read the installed role TOML and check discovery in the intended scope. Through an app-server for the same account and client, request `model/list` with `includeHidden: true` and collect all pages into one `{"data": [...]}` JSON result. Run `python3 adapters/codex/check_role.py <installed-role.toml> < model-list.json`. For an inherited model, resolve it in the active session and pass `--inherited-model` and, if applicable, `--inherited-effort`. The catalog indicates advertised access; record a completed response separately when a live gate is required.

Copy `adapters/codex/optional/nstack_security_daybreak.toml` to the agents directory only if you intend to use that route. Explicitly select it for an authorized defensive task and pass `--daybreak-selected` to preflight. Require `availableAccessPrograms.cyber` to advertise `daybreakBlue`. Select the program for that session with `--cyber-access-program daybreak_blue` if required by the client. Keep the global program default off. If the role, model or access is unavailable, stop dispatch and report the reason. Model substitutions require an explicit choice.
