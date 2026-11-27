# nstack

[日本語](README.ja.md)

**Go deep. Build less. Verify more.**

An engineering toolkit for Codex, built on the foundations of pstack. nstack (natori-stack) is an independent adaptation of Lauren Tan (Poteto)’s work for Codex CLI. It includes 14 workflow skills, 12 engineering principles, and seven playbooks. Start with the smallest useful change and verify it through observable results.

Repository: [natori-hrj/nstack](https://github.com/natori-hrj/nstack) (planned home for v0.2.0).

## Quick start

1. Install the skills and agent files from a checkout using the commands below.
2. Open a new `codex` session in your project. Run `$setup-nstack` to check discovery and review your model settings.
3. Give `$natori-mode` a task with an observable outcome. For example, `$natori-mode Fix the duplicate rows when an import is retried. Show the failing and passing checks.`

### Install at user scope

Run from this checkout. Existing paths are skipped. Keep both MIT notices with redistributed copies.

```sh
config_dir="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$config_dir/skills" "$config_dir/agents"
cp -n LICENSE "$config_dir/nstack-LICENSE"
cp -n LICENSE-upstream "$config_dir/nstack-LICENSE-upstream"
for skill in skills/*; do
  dest="$config_dir/skills/${skill##*/}"
  if [ ! -e "$dest" ] && [ ! -L "$dest" ]; then cp -R "$skill" "$dest"; fi
done
for agent in examples/agents/*.toml; do
  dest="$config_dir/agents/${agent##*/}"
  if [ ! -e "$dest" ] && [ ! -L "$dest" ]; then cp "$agent" "$dest"; fi
done
```

### Upgrading from v0.1.0

Follow the [migration guide](docs/migration.md) before installing into an existing Codex environment. It covers direct and plugin installations, preservation of customized model settings, and rollback.

The example agents use Sol for implementation, Daybreak Blue for authorized defensive security, and Astra for independent review. The TOML files control model and reasoning effort. Publication and merging require explicit operator authorization.

[Skill reference, routing, and plugin installation](docs/skills.md) · [Codex compatibility](docs/codex.md) · [Upstream provenance](docs/upstream.md) · [MIT](LICENSE) · [Upstream MIT](LICENSE-upstream)
