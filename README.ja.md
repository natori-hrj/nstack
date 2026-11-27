# nstack

[English](README.md)

**Go deep. Build less. Verify more.**

nstack (natori-stack) は、Lauren Tan (Poteto) の pstack を土台にした独立の Codex CLI 向け開発ツールキットです。ワークフロースキル14件、原則12件、プレイブック7件を収録しています。必要な変更を小さく絞り、観測できる結果で検証します。

リポジトリの移転予定先は [natori-hrj/nstack](https://github.com/natori-hrj/nstack) です。

## クイックスタート

1. このチェックアウトで以下を実行し、ユーザー領域に配置します。同名ファイルは保持します。
2. 対象プロジェクトで新しく `codex` を起動し、`$setup-nstack` で検出とモデル設定を確認します。
3. `$natori-mode インポート再試行時の重複行を修正し、修正前後のチェックを示して` のように、観測できる結果を添えて依頼します。

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

## v0.1.0 からの移行

既存環境へ導入する前に[移行ガイド](docs/migration.ja.md)を参照してください。直接導入とプラグイン導入、モデル設定の引き継ぎ、切り戻しの手順を記載しています。

モデル設定例は実装に Sol、許可された防御作業に Daybreak Blue、独立レビューに Astra を使います。モデルと推論強度は TOML で設定します。公開とマージには運用者の明示的な許可が必要です。再配布時は両方の MIT 通知を同梱してください。

[スキル一覧・振り分け・プラグイン導入](docs/skills.ja.md) · [Codex 互換性](docs/codex.ja.md) · [上流と出典](docs/upstream.ja.md) · [MIT](LICENSE) · [上流 MIT](LICENSE-upstream)
