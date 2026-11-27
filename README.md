# pstack-codex

Lauren Tan (Poteto) の pstack を Codex CLI で使う独立配布。既存の仕組みを活かし、短い作業単位を実行可能な証拠で検証します。

## インストール

配布のチェックアウトで、内容を確認してから以下を実行します。既存の同名ファイルを上書きしない手順です。ユーザー全体に配置する例で、プロジェクト限定ならスキルを対象リポジトリの `.agents/skills/`、エージェントを `.codex/agents/`、両方のライセンスを `pstack-codex-` を付けた名前でリポジトリのルートに配置します。

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

新しい Codex セッションで `$setup-pstack` を選択します。次のようにタスクを渡します。

- `$poteto-mode この集計の不具合を再現して、修正後の回帰チェックまで実行して`
- `$interrogate この差分を独立レビューし、各指摘を再現して`
- `$swarm 独立した2件を、担当と worktree を分けて検証して`
- `$autopilot-stack 依存順に候補を準備し、公開前の品質ゲートで止めて`

### ネイティブプラグインとして導入

既存のローカルマーケットプレイスを使う場合は、対象チェックアウトをマーケットプレイス配下に置き、その `.agents/plugins/marketplace.json` にローカルソースとして登録します。以下はマーケットプレイスのルートに配布一式を置いた場合のマニフェスト例です。

```json
{
  "name": "pstack-local",
  "plugins": [{
    "name": "pstack-codex",
    "source": {"source": "local", "path": "./"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity"
  }]
}
```

```sh
codex plugin marketplace add /絶対パス/ローカルマーケットプレイス
codex plugin add pstack-codex@pstack-local
```

プラグインはスキルを導入します。カスタムエージェントは上の TOML 配置手順を使います。再配布時は両方の MIT ライセンスを同梱してください。

## モデルと並行実行

| カスタムエージェント | 用途 | 設定例 |
|---|---|---|
| `pstack_implement` | 一般実装、機能、リファクタリング、テスト、文書 | `gpt-6.2-sol` |
| `pstack_security` | 防御的なセキュリティ実装と修正 | `gpt-daybreak-blue-latest` |
| `pstack_review` | コード、設計、反証のレビュー | `gpt-6.2-astra` |

配置した各 TOML の `model` と `model_reasoning_effort` を編集できます。役割をさらに細分化する場合は別のファイル名と `name` で設定を複製します。モデルが利用できない場合は作業を止め、利用可能なモデルを明示的に選ぶか、`model` を削除して継承を選びます。並列数は既存の Codex 設定の `[agents]` に `max_threads = 3` と `max_depth = 1` を追加する例を出発点にできます。別 CLI プロセスで動く書き込み担当の並列数は運用者が制限します。

## 構成

- ワークフロー14件と原則12件。対象のプレイブックと関連原則を必要なときに読み込みます。
- プレイブックは bug-fix、feature、refactoring、babysit、autopilot-stack、session-pickup、pause-safely。
- Codex プラグイン用マニフェストは `.codex-plugin/plugin.json`。直接インストールとローカルマーケットプレイス経由の両方を検証済みです。
- 検証は `python3 tests/validate.py`。Python 3.11+、Git、Codex CLI が必要です。配布自体の実行に追加ランタイムは不要です。

[Codex アダプターと検証](docs/codex.md) · [上流・ポート比較・同期](docs/upstream.md) · [MIT](LICENSE) · [上流 MIT](LICENSE-upstream)
