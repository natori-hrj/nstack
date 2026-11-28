# nstack

[日本語](README.ja.md)

**Go deep. Build less. Verify more.**

An engineering toolkit for Codex, built on the foundations of pstack. nstack (natori-stack) is an independent adaptation of Lauren Tan (Poteto)’s work for Codex CLI. It includes 14 workflow skills, 12 engineering principles, and seven playbooks. Start with the smallest useful change and verify it through observable results.

[GitHub repository](https://github.com/natori-hrj/nstack)

## Quick start

1. Install the skills and agent files from a checkout using the commands below.
2. Open a new `codex` session in your project. Run `$setup-nstack` to check discovery and review your model settings.
3. Give `$natori-mode` a task with an observable outcome. For example, `$natori-mode Fix the duplicate rows when an import is retried. Show the failing and passing checks.`

### Install at user scope

Run from this checkout. Use Python 3.11+ and PyYAML on a POSIX host. For an existing installation, read the migration guide before activation. Keep both MIT notices with redistributed copies.

```sh
(
  set -e
  config_dir="${CODEX_HOME:-$HOME/.codex}"
  revision="$(git rev-parse HEAD)"
  python3 adapters/codex/install.py --home "$config_dir" stage "$revision"
  python3 adapters/codex/install.py --home "$config_dir" activate "$revision"
  mkdir -p "$config_dir/agents"
  for agent in examples/agents/*.toml; do
    dest="$config_dir/agents/${agent##*/}"
    if [ ! -e "$dest" ] && [ ! -L "$dest" ]; then
      (set -C; cat "$agent" > "$dest") || exit 1
    fi
  done
)
```

## Standalone Go binary

Build with Go 1.25 or later (CI uses Go 1.27.4). Linux amd64 is execution-tested; Linux arm64 is cross-built but has not been tested on hardware. Other operating systems are unsupported. Use the same source bytes and toolchain to reproduce the binaries without checkout metadata or host paths:

```sh
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOAMD64=v1 \
  go build -mod=vendor -trimpath -buildvcs=false -o nstack-linux-amd64 ./cmd/nstack-codex
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 GOARM64=v8.0 \
  go build -mod=vendor -trimpath -buildvcs=false -o nstack-linux-arm64 ./cmd/nstack-codex
sha256sum nstack-linux-amd64 nstack-linux-arm64 > SHA256SUMS
sha256sum -c SHA256SUMS
```

Name the binary for your architecture `nstack`. `nstack --version` prints the distribution version and the embedded asset SHA-256 revision. Use the same explicit Codex home as the Python installer:

```sh
config_dir="${CODEX_HOME:-$HOME/.codex}"
revision="$(nstack --version | sed -n 's/.*assets sha256://p')"
nstack install --home "$config_dir" stage "$revision"
nstack install --home "$config_dir" activate "$revision"
```

Staging copies the skills, principles, playbooks, adapter references, docs, example roles and both MIT notices. The embedded plugin manifest identifies the distribution and is not an extra file in the interoperable snapshot. Stage a new ID to upgrade; activate a previous complete snapshot to roll back. Nothing in `agents` is written by the installer.

The binary does not run Python or PyYAML. `review` still needs Git, the Codex CLI and its existing OAuth login, your gate tools, and `gh` if delivering a PR. Managed paths need Linux procfs, flock and atomic rename support; Go staging also requires user extended attributes. Go stores a snapshot checksum on its directory so existing Python file-list comparisons are unchanged. For Python-era snapshots that lack a checksum, activation checks required files, skill metadata, and the presence of skill instructions; it cannot verify historical checksums. Managed directories must be owned by the current user and cannot be writable by others. Both installers share a lock; do not edit managed paths while either runs. A killed process can leave private scratch outside discovery; atomic activation does not establish power-loss durability. Redistribute both project MIT notices and the [TOML](vendor/github.com/BurntSushi/toml/COPYING) and [YAML license](vendor/go.yaml.in/yaml/v3/LICENSE) and [notice](vendor/go.yaml.in/yaml/v3/NOTICE).

### Upgrading and rolling back

Follow the [migration guide](docs/migration.md) before installing into an existing Codex environment. It covers direct and plugin installations, preservation of customized model settings, and rollback.

The default role examples use Sol for implementation and defensive work and Astra for review. You can edit the installed role TOMLs independently. Daybreak Blue is opt-in. Follow repository authorization for branch delivery and obtain explicit approval for release publication and merging. [Harness adapter contract](docs/adapters.md).

[Skill reference, routing, and plugin installation](docs/skills.md) · [Codex compatibility](docs/codex.md) · [Upstream provenance](docs/upstream.md) · [MIT](LICENSE) · [Upstream MIT](LICENSE-upstream)

[v0.3.0 commands and release notes](docs/v0.3.0.md)
