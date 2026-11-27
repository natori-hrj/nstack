# Harness adapters

[日本語](adapters.ja.md)

The shared workflow is the Markdown under `skills/`: acceptance, protected actions, task ownership, review budget and candidate evidence. The adapter maps that contract to native host operations. Project instructions and the effective permission policy govern each action.

| Operation | Adapter contract | Codex | Cursor / Claude Code / OpenCode |
|---|---|---|---|
| Discovery | Install and invoke the same workflow. Verify the resolved skill path. | Native skills and plugins. | Unevaluated for nstack. |
| Roles | Resolve the role, model, effort and effective access before dispatch. Report a missing route. | Custom agent TOMLs and active model catalog. | Unevaluated. |
| Isolation | Require an enforced read-only reviewer and separate writable scopes for concurrent writers. | Native sandbox plus separate sessions and worktrees. | Unevaluated. |
| Lifecycle | Resume and stop sessions with native controls. Keep worktree and revision evidence. | Codex CLI or the client hosting the session. | Unevaluated. |
| Delivery | Use the repository's authorized Git and PR operations; bind evidence to the exact candidate and compare the remote head. | Git and available GitHub tools. | Requires host verification. |

If writer isolation is unavailable, run serially. If required review, authorization or provider access is unavailable, keep the verified local evidence and report the blocker. Verify invocation, permissions and acceptance through the real host before declaring support. nstack currently ships the [Codex adapter](codex.md).

For each delivery candidate record the base SHA, candidate SHA, command and result for each gate, reviewer and reviewed SHA, and known limitations. Compare the PR head to the verified local SHA before calling it ready. A changed head invalidates evidence for affected behavior. Repository and host rules determine who may commit, push a feature branch, open a PR or perform a gated operation.

The host workflow in `adapters/review_workflow.py` calls the adapter's `preflight`, `gate` and `run` operations. An adapter must fail when it cannot establish the selected model and permissions, isolate each review context, enforce read-only review, and return thread/session evidence and the schema-constrained result. The host controls Git, candidate binding, review budgets and authorized delivery. The Codex adapter uses the native app-server protocol.
