# Codex アダプター

[English](codex.md)

| 上流の手段 | Codex での扱い |
|---|---|
| スキル呼び出し | `$名前`。別の手順を参照する場合は対象の SKILL.md またはプレイブックを読む |
| Task / model rules | 利用可能なネイティブサブエージェントを名前で選ぶ。ロールのモデルと推論強度は TOML |
| 並列書き込み | 担当ごとに固有のブランチと Git worktree を割り当て、`codex -C <worktree>` で別セッションを開く |
| 読み取り専用レビュー | 読み取り専用の親セッションから呼ぶ `nstack_review`、または `codex exec -C <worktree> --sandbox read-only -m <model>` |
| スキーマ付き出力 | 必要なときに `codex exec --output-schema <file>` |
| セッション再開 | `codex resume <session-id>`。非対話セッションは `codex exec resume <session-id>` |
| Cursor Cloud、Bugbot、Automations、トランスクリプト連携 | 対象外。利用できる CI・レビュー証跡を読み取り、状態を報告する |

CLI 0.172.0 のヘルプには管理 worktree 用の `--worktree` もあります。手動 Git worktree は同じ起点と担当ブランチを明示する必要のあるタスクに使います。Git worktree 自体は権限境界ではありません。各セッションの実効サンドボックスを確認し、兄弟ディレクトリを `--add-dir` で書き込み対象に加えないでください。同じファイルを変更するタスクは直列化します。権限やモデルがホスト設定で固定されている場合はその制約を記録します。

納品前に最終候補の revision を固定し、必須品質ゲートを一度通します。候補が変わった場合は影響する証跡を更新します。コミット、担当ブランチへの push、PR 作成はリポジトリの権限に従います。リリース公開、マージ、破壊的な後片付けは明示的な許可を得ます。持ち込みの設定、フック、依存コマンド、エージェント出力は入力として扱い、実行前に確認します。パッケージにフック、MCP、API キー、外部サービス連携は含まれません。

## 検証と測定

オフライン検証は、Codex app-server の `skills/list`、マニフェストとモデル TOML の構文、独立したチェックアウトでの再現、2件の並列処理による隔離、親 HEAD とリモートの状態を確認します。並行ワーカーは決定的な Python fixture です。任意の停止判断や本番 CI はワークフローの指示に従います。

ライブでは CLI の明示的な `-m` で3モデルそれぞれが応答を完了しました。これは要求したモデル名で CLI リクエストが成功した証拠です。バックエンドの実体を独立に識別する証拠はありません。リリース前の追加検証では、ユーザー用 agents ディレクトリからネイティブのロール名を指定し、Sol と Astra の応答とセッション記録のモデル名を確認しました。Daybreak Blue は、一時環境でプログラムを指定しなかったときに `access_programs.cyber=daybreak_blue` を要求されました。認証済みの Codex の `model/list` で対象モデルの `availableAccessPrograms.cyber` に `daybreakBlue` があることを確認し、CLI 0.172.0 の `--cyber-access-program daybreak_blue` を指定した読み取り専用セッションで、ネイティブの `pstack_security` がモデル上書きなしで応答することを確認しました。アクセスプログラムの選択は利用権限を付与しません。権限が確認できない場合はそのロールの作業を止めます。

比較実験では各実行の開始・終了時刻を記録し、`codex exec --json` の `turn.completed.usage` で入力、キャッシュ済み入力、出力を集計します。非キャッシュ入力は入力からキャッシュ済み入力を引きます。担当の起動回数、レビュー回数、人間の介入、受け入れ検証まで完了したタスク数を同じ基準で手集計します。セッション ID やログはリポジトリの外に置きます。同条件の比較結果が揃うまで効率改善は判断しません。

[公式 Skills](https://learn.chatgpt.com/docs/build-skills) · [公式 Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) · [公式 Plugins](https://learn.chatgpt.com/docs/plugins) · [公式設定リファレンス](https://learn.chatgpt.com/docs/config-file/config-reference)

| ライブ実行 | 入力 | キャッシュ済み | 非キャッシュ | 出力 |
|---|---:|---:|---:|---:|
| Sol 応答 smoke | 19,972 | 7,296 | 12,676 | 5 |
| Astra 応答 smoke | 19,921 | 7,296 | 12,625 | 5 |
| Daybreak Blue 応答 smoke | 15,517 | 11,392 | 4,125 | 5 |
| Astra の独立レビュー | 61,342 | 47,872 | 13,470 | 204 |
| 合計 | 116,752 | 73,856 | 42,896 | 219 |

独立レビューは `$interrogate` を読み、`total(2, 3)` の実測値 −1 と期待値 5 の差を報告して1回で終了しました。ライブ実行は4回、レビューは1回、fixture の検証済み並行タスクは2件。人間の介入回数と各ライブ実行の正確な所要時間は記録していません。

[公式 Daybreak CLI ガイド](https://help.openai.com/en/articles/20001607-using-daybreak-in-codex-cli)

## 起動前のロール確認

導入した TOML と、対象スコープでの検出を確認します。同じアカウントとクライアントの app-server で `includeHidden: true` を付けて `model/list` を取得し、全ページを `{"data": [...]}` にまとめます。`python3 adapters/codex/check_role.py <導入済みロール.toml> < model-list.json` を実行します。モデルが継承設定なら実セッションで解決し、`--inherited-model` と、該当する場合は `--inherited-effort` に渡します。モデル一覧は公示されたアクセスの証拠です。ライブゲートが必要な場合は、応答完了を別途記録します。

`adapters/codex/optional/nstack_security_daybreak.toml` は利用する場合に agents ディレクトリへ配置します。許可された防御作業に明示的に選択し、事前確認に `--daybreak-selected` を付けます。`availableAccessPrograms.cyber` に `daybreakBlue` があることを確認します。クライアントが要求する場合は、そのセッションに `--cyber-access-program daybreak_blue` を指定します。グローバル既定は無効のままにします。ロール、モデル、アクセスが不足している場合は起動を停止し、理由を報告します。モデルの代替には明示的な選択が必要です。
