# nstack

[English](README.md)

**Go deep. Build less. Verify more.**

nstack (natori-stack) は、Lauren Tan (Poteto) の pstack を土台にした独立の Codex CLI 向け開発ツールキットです。ワークフロースキル14件、原則12件、プレイブック7件を収録しています。必要な変更を小さく絞り、観測できる結果で検証します。

[GitHub リポジトリ](https://github.com/natori-hrj/nstack)

## クイックスタート

1. Python 3.11 以降と PyYAML がある POSIX 環境で、以下をこのチェックアウトから実行します。既存環境では有効化前に移行ガイドを参照してください。
2. 対象プロジェクトで新しく `codex` を起動し、`$setup-nstack` で検出とモデル設定を確認します。
3. `$natori-mode インポート再試行時の重複行を修正し、修正前後のチェックを示して` のように、観測できる結果を添えて依頼します。

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

## 更新と切り戻し

既存環境へ導入する前に[移行ガイド](docs/migration.ja.md)を参照してください。直接導入とプラグイン導入、モデル設定の引き継ぎ、切り戻しの手順を記載しています。

モデル設定例は実装と防御作業に Sol、独立レビューに Astra を使います。導入済み TOML は個別に編集できます。Daybreak Blue は任意です。ブランチの納品はリポジトリの権限に従い、リリース公開とマージには明示的な許可を得ます。再配布時は両方の MIT 通知を同梱してください。[ホストアダプター契約](docs/adapters.ja.md)

[スキル一覧・振り分け・プラグイン導入](docs/skills.ja.md) · [Codex 互換性](docs/codex.ja.md) · [上流と出典](docs/upstream.ja.md) · [MIT](LICENSE) · [上流 MIT](LICENSE-upstream)

[v0.3.0 のコマンドとリリースノート](docs/v0.3.0.md)
