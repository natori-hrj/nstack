# pstack-codex

[日本語](README.ja.md)

An independent Codex CLI adaptation of Lauren Tan (Poteto)’s pstack. It includes 14 workflow skills, 12 engineering principles, and seven playbooks for evidence-based engineering.

## Quick start

1. Install the skills and agent files from a checkout using the commands below.
2. Open a new `codex` session in your project. Run `$setup-pstack` to check discovery and review your model settings.
3. Give `$natori-mode` a task with an observable outcome. For example, `$natori-mode Fix the duplicate rows when an import is retried. Show the failing and passing checks.`

### Install at user scope

Run from this checkout. Existing paths are skipped. Keep both MIT notices with redistributed copies.

```sh
config_dir="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$config_dir/skills" "$config_dir/agents"
cp -n LICENSE "$config_dir/pstack-codex-LICENSE"
cp -n LICENSE-upstream "$config_dir/pstack-codex-LICENSE-upstream"
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

Install from a checkout containing `natori-mode`, then replace `$poteto-mode` in your prompts with `$natori-mode`. For direct installations, the copy commands skip existing paths. Update the four installed wrappers (`babysit`, `autopilot-stack`, `session-pickup`, `pause-safely`) from the new checkout so they point to the renamed playbooks. Back up local edits before replacing any files. Once verified, move the old installed `poteto-mode` directory outside your skills search paths and start a new session. For a plugin installation, update the plugin from the new source and start a new session.

The example agents use Sol for implementation, Daybreak Blue for authorized defensive security, and Astra for independent review. The TOML files control model and reasoning effort. Publication and merging require explicit operator authorization.

[Skill reference, routing, and plugin installation](docs/skills.md) · [Codex compatibility](docs/codex.md) · [Upstream provenance](docs/upstream.md) · [MIT](LICENSE) · [Upstream MIT](LICENSE-upstream)
