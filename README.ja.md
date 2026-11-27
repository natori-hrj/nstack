# pstack-codex

[English](README.md)

Lauren Tan (Poteto) の pstack を Codex CLI 向けに移植した独立配布です。検証可能な開発のためのワークフロースキル14件、原則12件、プレイブック7件を収録しています。

## クイックスタート

1. このチェックアウトで以下を実行し、ユーザー領域に配置します。同名ファイルは保持します。
2. 対象プロジェクトで新しく `codex` を起動し、`$setup-pstack` で検出とモデル設定を確認します。
3. `$natori-mode インポート再試行時の重複行を修正し、修正前後のチェックを示して` のように、観測できる結果を添えて依頼します。

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

## v0.1.0 からの移行

`natori-mode` を含むチェックアウトからインストールし、プロンプトの `$poteto-mode` を `$natori-mode` に置き換えます。直接インストールでは既存ファイルがスキップされるため、`babysit`、`autopilot-stack`、`session-pickup`、`pause-safely` の4件も新しいチェックアウトから更新し、改名後のプレイブックを参照できるようにします。ローカル編集は置き換え前に退避してください。確認後、インストール済みの旧 `poteto-mode` ディレクトリをスキルの検索範囲外に移し、新規セッションを起動します。プラグイン経由の場合は新しいソースからプラグインを更新し、新規セッションを起動します。

モデル設定例は実装に Sol、許可された防御作業に Daybreak Blue、独立レビューに Astra を使います。モデルと推論強度は TOML で設定します。公開とマージには運用者の明示的な許可が必要です。再配布時は両方の MIT 通知を同梱してください。

[スキル一覧・振り分け・プラグイン導入](docs/skills.ja.md) · [Codex 互換性](docs/codex.md) · [上流と出典](docs/upstream.md) · [MIT](LICENSE) · [上流 MIT](LICENSE-upstream)
