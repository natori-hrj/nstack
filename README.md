# nstack

[日本語](README.ja.md)

**Go deep. Build less. Verify more.**

nstack is a Go-based engineering toolkit for agent-assisted development, built on Lauren Tan (Poteto)’s pstack. Its shared library contains 14 workflow skills, 12 engineering principles, and seven playbooks. Define an observable outcome, make the smallest useful change, and verify the exact candidate.

| Harness | Workflow Support | Native Automation |
|---|---|---|
| [Codex](docs/codex.md) | Skills, roles and manual workflow | Go `nstack review` and `check-role` using the Codex adapter |
| [OpenCode v2](docs/opencode.md) | Managed skills and an operator-led workflow | Unavailable ([#12](https://github.com/natori-hrj/nstack/issues/12)) |
| Claude Code | Unavailable | [Deferred (#13)](https://github.com/natori-hrj/nstack/issues/13) |
| Grok Build | Unavailable | [Deferred (#14)](https://github.com/natori-hrj/nstack/issues/14) |

**Workflow Support** installs the shared instructions and documents how to apply them in a host. **Native Automation** means nstack can enforce the review and delivery contract through an adapter. OpenCode review is a separate, operator-led read-only handoff; nstack does not certify its verdict schema, parallel writer isolation, or delivery. If a mandatory automation capability is missing, stop that run.

## Install from the single binary

Use the appropriate [release asset](https://github.com/natori-hrj/nstack/releases) as `nstack` and verify its SHA-256 before running it. Linux amd64 is execution-tested; Linux arm64 is cross-built only. Other OSes are unsupported. `nstack --version` prints the version and canonical embedded asset digest.

For Codex:

```sh
(
  set -e
  config_dir="${CODEX_HOME:-$HOME/.codex}"
  snapshot="$(nstack --version)"
  snapshot="${snapshot##*sha256:}"
  nstack install --home "$config_dir" stage "$snapshot"
  nstack install --home "$config_dir" activate "$snapshot"
)
```

In a fresh Codex session run `$setup-nstack`, then `$natori-mode` with your acceptance check. For OpenCode installation, role settings and `@natori-mode`, see the [OpenCode guide](docs/opencode.md). Model and reasoning settings are user-controlled; the installer does not write role or authentication settings.

Stage a new snapshot ID and activate it to update. Activate a previous complete ID to roll back. Both hosts can coexist at separate homes. For old direct copies, plugins, or Python-managed snapshots, see the [migration guide](docs/migration.md). Resolve duplicate skill sources before activating and verify the resolved paths in the host.

The binary needs no Python, PyYAML or Go toolchain at runtime. Workflow Support still needs the chosen harness; Codex automation needs Git, Codex CLI with approved OAuth, your quality-gate commands, and `gh` for PR delivery. The installer needs Linux procfs, flock, atomic rename and user extended attributes, and managed directories owned by the current user and writable only by that user. Staging is outside discovery; an interruption may leave private scratch. Atomic activation is not a guarantee of power-loss durability.

## Standalone Go binary

Use Go 1.25 or later (verification pins Go 1.27.4). Build from the exact approved source:

```sh
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOAMD64=v1 \
  go build -mod=vendor -trimpath -buildvcs=false -o nstack-linux-amd64 ./cmd/nstack-codex
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 GOARM64=v8.0 \
  go build -mod=vendor -trimpath -buildvcs=false -o nstack-linux-arm64 ./cmd/nstack-codex
sha256sum nstack-linux-amd64 nstack-linux-arm64 > SHA256SUMS
sha256sum -c SHA256SUMS
```

See [release preparation](docs/releases/v0.4.0.md) for reproduction and notices, and the [adapter contract](docs/adapters.md) for quality and delivery boundaries.

[Skills](docs/skills.md) · [Upstream provenance](docs/upstream.md) · [MIT](LICENSE) · [Upstream MIT](LICENSE-upstream) · [v0.3.0 reference](docs/v0.3.0.md)
