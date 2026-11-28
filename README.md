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

### Upgrading and rolling back

Follow the [migration guide](docs/migration.md) before installing into an existing Codex environment. It covers direct and plugin installations, preservation of customized model settings, and rollback.

The default role examples use Sol for implementation and defensive work and Astra for review. You can edit the installed role TOMLs independently. Daybreak Blue is opt-in. Follow repository authorization for branch delivery and obtain explicit approval for release publication and merging. [Harness adapter contract](docs/adapters.md).

[Skill reference, routing, and plugin installation](docs/skills.md) · [Codex compatibility](docs/codex.md) · [Upstream provenance](docs/upstream.md) · [MIT](LICENSE) · [Upstream MIT](LICENSE-upstream)

[v0.3.0 commands and release notes](docs/v0.3.0.md)
