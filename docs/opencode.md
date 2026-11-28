# OpenCode v2 Workflow Support

[日本語](opencode.ja.md) · [Support matrix](../README.md)

## Install and verify one source

Before activating, inspect the effective skill paths in the intended project. The optional `jq` command below URL-encodes the project path for OpenCode's API. Check global and project `.opencode`, `.claude` and `.agents` skill directories and explicit `skills` sources in OpenCode configuration. Remove old nstack entries from discovery yourself, or move the old files outside discovery and keep a backup. In particular, replace any previous `skills` entry pointing to a checkout or snapshot; OpenCode gives explicit sources higher priority. Leave unrelated settings and Codex's managed home alone.

```sh
location="$(jq -nr --arg directory "$PWD" '$directory|@uri')"
opencode api get "/api/skill?location%5Bdirectory%5D=$location" | jq -r '.data[] | [.id,.path] | @tsv'
```

```sh
(
  set -e
  config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
  snapshot="$(nstack --version)"
  snapshot="${snapshot##*sha256:}"
  nstack install --harness opencode --home "$config_dir" stage "$snapshot"
  nstack install --harness opencode --home "$config_dir" activate "$snapshot"
)
```

OpenCode discovers `skills/nstack-managed`; the atomic link selects a complete snapshot under `nstack/snapshots`. Do not also add it to `skills` in the configuration. Repeating the same stage/activate is safe; use a new ID for an upgrade and activate a previous complete ID to roll back. The installer rejects conflicts in the selected skills directory, including same-ID root Markdown files. It leaves other search roots and config untouched; it cannot prevent shadowing by project, compatible, remote, or explicitly configured sources. After `/reload` or in a fresh location, wait for discovery to load and confirm all 26 nstack IDs, including `natori-mode`, resolve to the active snapshot. If a path differs, stop and resolve the duplicate before using the workflow. Do not activate the same library at both project and user scope.

## Select roles and run serially

1. Start a session in the target project. Use `@setup-nstack` to inventory the active paths, identity, model and access. Use `@natori-mode` with an observable acceptance check. The skill links to local playbooks and calls the shared skills; use OpenCode's `@skill-id` or `skill` tool when following a shared skill reference.
2. Choose your implementation model and reasoning variant in your client. For persistent roles, add the following **example** entries to your own `opencode.json(c)` with actual provider/model IDs and variants available to your account. Keep unrelated settings; verify the session's effective selection. A standalone review session must explicitly select the review model and variant; changing its agent alone may keep the previous model.

```json
{
  "agents": {
    "nstack-implement": {
      "description": "Serial implementation against an observable acceptance check",
      "mode": "primary",
      "model": "provider/implementation-model#variant"
    },
    "nstack-review": {
      "description": "Independent review of an exact candidate",
      "mode": "all",
      "model": "provider/review-model#variant",
      "permissions": [
        {"action":"*","resource":"*","effect":"deny"},
        {"action":"read","resource":"*","effect":"allow"},
        {"action":"glob","resource":"*","effect":"allow"},
        {"action":"grep","resource":"*","effect":"allow"},
        {"action":"skill","resource":"*","effect":"allow"},
        {"action":"external_directory","resource":"ABSOLUTE_MANAGED_LINK/*","effect":"allow"},
        {"action":"external_directory","resource":"ABSOLUTE_ACTIVE_SNAPSHOT/*","effect":"allow"}
      ]
    }
  }
}
```

If your policy denies `external_directory`, run this lookup after activation and use its two values in the role rules. OpenCode can reference a supporting file through the managed link or its resolved path. Keep the reviewer’s write tools denied and recheck the paths after an update. The `skill` permission alone does not grant reads of supporting files.

```sh
(
  set -eu
  config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
  managed_link="$config_dir/skills/nstack-managed"
  if [ ! -L "$managed_link" ] || ! active_skills="$(readlink -e -- "$managed_link")" || [ ! -d "$active_skills" ]; then
    printf 'No active OpenCode skill snapshot at %s\n' "$managed_link" >&2
    exit 1
  fi
  printf 'ABSOLUTE_MANAGED_LINK=%s\n' "$managed_link"
  printf 'ABSOLUTE_ACTIVE_SNAPSHOT=%s\n' "${active_skills%/*}"
)
```

3. Apply Behavior First: state the expected result, check it through the normal entry point, and record the verification. Keep one writer. Freeze the full diff and untracked inputs or the exact revision; hand the candidate, acceptance checks and results to a fresh independent read-only review session. Make the evidence accessible from that session's location. Verify effective tools and enforce read-only access separately if required; role configuration alone does not prove filesystem confinement. Stop if required permissions cannot be established.
4. Keep the review budget: initial review and at most two fix-and-recheck rounds by default. Repeat affected gates and review after fixes. Record the reviewed candidate, effective model/variant, session and response, findings and blockers. Commits, push and PRs follow repository authorization; merges, release publication and destructive actions need explicit authorization. Verify the exact delivered SHA before declaring delivery.

This is an operator-led workflow. OpenCode 2.4.2 did not enforce the requested arbitrary verdict schema in the tested session path, and parallel writer confinement is unproved. A manual review or local JSON check does not meet the Native Automation contract. `nstack review` uses Codex; no OpenCode adapter or automatic fallback exists.

[OpenCode skills](https://opencode.ai/docs/skills) · [Agents](https://opencode.ai/docs/agents) · [Models](https://opencode.ai/docs/models)
