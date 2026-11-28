# OpenCode v2 Workflow Support

[English](opencode.md) · [対応表](../README.ja.md)

## 導入と探索先の照合

有効化前に対象プロジェクトで実効スキルパスを確認します。次の確認例では `jq` でパスを URL エンコードします。ユーザーとプロジェクトの `.opencode`、`.claude`、`.agents` のスキル、設定の `skills` ソースも確認してください。旧 nstack の登録を自分で外すか、探索対象外に退避します。特に旧チェックアウトやスナップショットを指す明示的な `skills` は優先されます。無関係な設定や Codex 側の管理先はそのままにします。

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

OpenCode は `skills/nstack-managed` を標準探索します。リンクは `nstack/snapshots` 内の完全なスナップショットに原子的に切り替わります。このリンクを `skills` にも追加しないでください。同じ ID で再実行でき、更新は新しい ID、切り戻しは以前の完全な ID の有効化です。指定先のスキルディレクトリでは同じ ID の直下 Markdown も含め競合を拒否します。別の探索先や設定は変更しないため、プロジェクト、互換、リモート、明示設定による上書きは別途確認が必要です。`/reload` または新しい場所での起動後、探索完了を待ち、`natori-mode` を含む26件が有効なスナップショットを指すことを確認します。異なるパスなら利用前に重複を解消してください。ユーザーとプロジェクトの両方で同じライブラリを有効化しないでください。

## ロールと直列ワークフロー

1. `@setup-nstack` で探索先、ロール、モデル、アクセスを確認し、観測可能な受け入れ条件を添えて `@natori-mode` を起動します。個別の共通スキルは `@skill-id` または `skill` ツールで読みます。
2. 実装・レビューのモデルと推論強度はクライアントで選びます。永続化する場合は [英語版のロール設定例](opencode.md#select-roles-and-run-serially)を、自分の `opencode.json(c)` に必要な部分だけ追加します。`provider/model#variant` は利用可能な設定に置き換え、実効値を確認します。独立したレビューセッションではロールの切り替えだけに頼らず、モデルと推論強度を明示して選択してください。
3. Behavior First に従い、期待結果を定義して通常の入口から検証します。書き込み担当は一人とし、候補 revision、または完全な差分と未追跡の入力を固定します。別の読み取り専用セッションに、候補・受け入れ条件・検証結果を渡します。その場所から証跡が読めることを確認してください。設定だけでファイルシステム隔離を保証せず、必要なら別途読み取り専用境界を強制します。必須の権限を確認できなければ停止します。
4. 初回レビュー後の修正・再確認は既定で最大2回です。修正後は影響するゲートとレビューをやり直します。候補、実効モデルと推論強度、セッションと応答、指摘とブロッカーを記録します。コミット・push・PR はリポジトリの許可に従い、マージ・リリース公開・破壊的操作には明示の許可を得ます。納品対象が検証した SHA と一致することを照合します。

`external_directory` を拒否するロールでは、有効化後に次のコマンドを実行し、表示された2つのパスをロール設定例に使います。OpenCode は付属ファイルを管理リンク経由またはリンク先のパスで読みます。レビュー側の書き込みは拒否したままにし、更新後はパスを再確認します。`skill` の許可だけでは付属ファイルを読めません。

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

これは操作者主導の手順です。OpenCode 2.4.2 の検証したセッション経路では任意の出力スキーマは強制されず、並列書き込み隔離も未実証です。手動レビューやローカル JSON 検証を Native Automation の代わりにはしません。`nstack review` は Codex を使い、OpenCode Adapter と自動フォールバックはありません。

[OpenCode スキル](https://opencode.ai/docs/skills) · [エージェント](https://opencode.ai/docs/agents) · [モデル](https://opencode.ai/docs/models)
