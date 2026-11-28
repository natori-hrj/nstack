# スキルリファレンス

[English](skills.md) · [クイックスタート](../README.ja.md)

## タスクに合うスキルを選ぶ

達成したい結果があり、進め方の選択を任せたいときは `$natori-mode` を明示的に呼び出します。Codex は依頼、リポジトリの指示、worktree の状態、既存の検証手段を確認し、受け入れチェックを決めて該当するプレイブックだけを読みます。バグ修正、機能追加、リファクタリングには専用のプレイブックがあります。調査は読み取り専用で進め、設計上の不確実性には `$architect` を使います。必要に応じて個別スキルや原則を参照します。自動振り分けは明示的な呼び出しの中で行われ、配布スキルの暗黙呼び出しは無効です。

- **不具合を証明・修正する** — 公開インターフェースで失敗を確認するなら `$tdd`、誤りが判明した主張を訂正するなら `$correct`、差分を独立検証するなら `$interrogate`。
- **変更を理解する** — 影響する契約は `$blast-radius`、設計判断は `$architect`、繰り返す教訓の定着は `$reflect`。
- **並行して進める** — 異なる独立タスクは `$swarm`、同じ課題に対する代替案の比較は `$arena`。後者は共通基準で比較し、採用パッチは運用者が選びます。
- **提出に備える** — `$babysit` は既存 PR の最新 head を追い、マージ可能または阻害要因が判明するまで確認します。`$autopilot-stack` は複数候補を依存順に準備します。既存 PR には babysit プレイブックを使い、検証済み候補の引き渡しで止まります。
- **セッションを管理する** — 導入確認は `$setup-nstack`、中断と引き継ぎは `$pause-safely`、再開は `$session-pickup`。

## ワークフロースキル

| スキル | 使う場面と入力例 | 期待する成果と終了条件 |
|---|---|---|
| [natori-mode](../skills/natori-mode/SKILL.md) | 一般的な開発。 `$natori-mode 再試行で重複するインポートを修正し、結果を確認して` | 成果、受け入れチェック、選んだ手順の検証証拠。証拠と残る制約を記録したら終了。 |
| [setup-nstack](../skills/setup-nstack/SKILL.md) | 初回起動やモデルの確認。 `$setup-nstack スキル検出とモデル割り当てを確認して` | 検出、モデル、推論強度、並列数を確認。要求したモデルとプロバイダーが確認した証拠を区別し、利用できない設定は明示的な選択を求める。 |
| [architect](../skills/architect/SKILL.md) | 重要な設計判断。 `$architect インポート検証を CLI 境界に移すべきか検討して` | 選んだ設計、トレードオフ、未解決の判断を記録。契約や範囲が変わる対立は判断を仰ぐ。 |
| [swarm](../skills/swarm/SKILL.md) | 独立タスク。 `$swarm CSV パーサーの修正とログガイドの更新を別々に進めて` | 依存関係、重複、担当、起点、差分、テスト、阻害要因。並列性が任意で直列実行が要件を満たす場合だけ直列化し、必須能力が不足すれば停止する。統合と公開は運用者へ引き渡す。 |
| [arena](../skills/arena/SKILL.md) | 同じ課題の代替案。 `$arena 引用符付きフィールドの解析方法を同じテストデータで二案比較して` | 合意した予算内で挙動、差分の大きさ、保守コストを比較。パッチ選択と worktree の片付けは運用者に委ねる。 |
| [interrogate](../skills/interrogate/SKILL.md) | 証拠に基づく独立レビュー。 `$interrogate この差分がインポート再試行の契約を満たすか確認して` | 場所、証拠、契約、可能なら再現方法、実測と期待、影響、根本原因を記録。共通原因をまとめ、任意の改善と区別する。実行が難しければ理由と静的証拠を示す。同じ前提で2回失敗したら前提を検証し、解決または明示的な引き継ぎで終了。 |
| [tdd](../skills/tdd/SKILL.md) | 意味のある挙動の回帰。 `$tdd 同じファイルを2回取り込んでも1件だけ保存されることをテストして` | 期待どおりの失敗を確認し、最小の根本修正後に通常の入口から再検証。公開候補では必須チェックを実行する。 |
| [blast-radius](../skills/blast-radius/SKILL.md) | 境界をまたぐ変更。 `$blast-radius この保存形式に依存する呼び出し元を調べて` | 直接・間接の影響、旧データ、副作用、復旧経路と、それらを確認する最小のチェック。観測と仮説を区別する。 |
| [correct](../skills/correct/SKILL.md) | 主張や実装の誤りが判明。 `$correct 再試行は冪等という例に反し、このデータでは重複するので直して` | 可能なら独立再現し、根本原因を直して再検証。同じ前提で2回失敗したら前提を検証する。 |
| [reflect](../skills/reflect/SKILL.md) | 失敗や教訓が繰り返される。 `$reflect インポート境界の回帰が繰り返された教訓を残して` | テスト、型、不変条件、簡素化に落とし込む。手順上の教訓は許可範囲で既存の指示を簡潔に更新する。 |
| [babysit](../skills/babysit/SKILL.md) | 既存 PR。 `$babysit PR 42 のマージ可否を調べて阻害要因を報告して` | 正確な head、CI、競合、レビューを追う。head が変われば再検証し、合意した範囲で既知の一時的失敗だけを再試行する。マージ可能または具体的な阻害要因で終了。 |
| [autopilot-stack](../skills/autopilot-stack/SKILL.md) | 依存する複数の PR 候補。 `$autopilot-stack パーサー変更を先に、その後に依存する CLI 変更を準備して` | 前提と担当を整理し、最終差分を独立レビューし、正確な候補に必須チェックを通す。依存順の引き渡しで終了。 |
| [session-pickup](../skills/session-pickup/SKILL.md) | 中断した作業の再開。 `$session-pickup 記録したセッション ID と引き継ぎから修正を再開して` | ID で再開するか最新の引き継ぎを参照。起点、worktree、担当、最後のチェックを確認し、古くなったチェックだけをやり直して続ける。 |
| [pause-safely](../skills/pause-safely/SKILL.md) | 作業の一時停止。 `$pause-safely 書き込み担当を停止し、明日のために引き継ぎを残して` | 新規作業を止め、進行中のセッションを中断。書き込み停止を確認し、ID、リビジョン、変更、検証、阻害要因、次の作業を記録する。worktree と編集を保持する。 |

プレイブックは [バグ修正](../skills/natori-mode/playbooks/bug-fix.md)、[機能追加](../skills/natori-mode/playbooks/feature.md)、[リファクタリング](../skills/natori-mode/playbooks/refactoring.md)、[PR 監視](../skills/natori-mode/playbooks/babysit.md)、[スタックの準備](../skills/natori-mode/playbooks/autopilot-stack.md)、[再開](../skills/natori-mode/playbooks/session-pickup.md)、[安全な中断](../skills/natori-mode/playbooks/pause-safely.md) の7件です。

## エンジニアリング原則

タスク中の判断に使い、得られた判断やチェック結果をワークフローの報告に含めます。

| スキル | 使う場面 | 成果・確認条件 |
|---|---|---|
| [principle-laziness-protocol](../skills/principle-laziness-protocol/SKILL.md) | 差分が膨らむ、判断が重複する。 | 判断を一か所に集め、必要十分な変更にする。 |
| [principle-foundational-thinking](../skills/principle-foundational-thinking/SKILL.md) | 型、データ形状、共有状態を決める前。 | アクセスパターンに合う形を選び、必要に応じて可変状態を隔離し、後工程に役立つ土台を先に用意する。 |
| [principle-attack-the-premise](../skills/principle-attack-the-premise/SKILL.md) | 同じ前提の修正が同じチェックで2回失敗。 | 次の修正前に前提を書き出し、直接検証する。 |
| [principle-subtract-before-you-add](../skills/principle-subtract-before-you-add/SKILL.md) | 追加や構造変更の前。 | 新しく作る前に不要なコードや重複を削る。 |
| [principle-boundary-discipline](../skills/principle-boundary-discipline/SKILL.md) | 検証、エラー処理、アダプターの実装。 | 境界で解析・検証し、内部を型付きの純粋なロジックに保つ。 |
| [principle-type-system-discipline](../skills/principle-type-system-discipline/SKILL.md) | 型付き API やドメインモデルの設計。 | 正当な状態を表現し、意味の異なるプリミティブを区別し、すべての変種を扱い、正本のスキーマから型を導出する。 |
| [principle-prove-it-works](../skills/principle-prove-it-works/SKILL.md) | 完了を宣言する前。 | 実際の成果物から直接証拠を得て、可能ならチェックをスクリプト化する。 |
| [principle-fix-root-causes](../skills/principle-fix-root-causes/SKILL.md) | 原因不明、または繰り返す症状。 | 再現し、最初の誤った判断や未処理の正当な状態を修正する。同じ欠陥の他の箇所も確認する。 |
| [principle-sequence-verifiable-units](../skills/principle-sequence-verifiable-units/SKILL.md) | 移行、一括変更、積み重なる差分。 | 小単位ごとに基準、変更、成功したチェックを揃えてから次へ進む。 |
| [principle-test-behavior-not-implementation](../skills/principle-test-behavior-not-implementation/SKILL.md) | テストの作成・評価。 | 観測可能な挙動が壊れれば失敗し、内部だけが変われば通るテストにする。 |
| [principle-guard-the-context-window](../skills/principle-guard-the-context-window/SKILL.md) | 大量の読み込み、出力、作業分割。 | 段階ごとにファイル数やターン数を制限する。大量の作業を委任した場合は主スレッドに要約を残す。 |
| [principle-encode-lessons-in-structure](../skills/principle-encode-lessons-in-structure/SKILL.md) | 指示や訂正が繰り返される。 | 強制できるルールは構造に組み込む。判断が必要なら指示を目立たせ、例を添える。 |

## モデル・隔離・公開権限

[設定例](../examples/agents/)では `nstack_implement` に Sol、許可された防御作業を担当する `nstack_security` に Sol、`nstack_review` に Astra を割り当てます。モデルと推論強度は配置先の TOML、サブエージェント数は Codex の `[agents]` で設定します。独立して起動する CLI セッション数は運用者が制限します。Daybreak には承認済みアクセスと適切なプログラム指定が必要です。必須モデルが利用できなければ作業を止めます。独立レビューは読み取り専用の親か別の読み取り専用セッションで行います。[Codex アダプター](codex.ja.md)

並行する書き込み担当には別ブランチ、別 worktree、別 Codex セッションを割り当てます。実効サンドボックスを確認し、兄弟 worktree を書き込み範囲に含めないでください。通常の GitHub 納品はリポジトリの権限に従います。リリース公開とマージは明示的な許可を得ます。Cursor Cloud、Bugbot、Cursor Automations はアダプターの対象外です。

## その他のインストール方法

プロジェクト限定の場合は、スキルを `.agents/skills/`、エージェント TOML を `.codex/agents/`、両方の MIT 通知を名前に `nstack-` を付けてプロジェクトルートに配置します。

ネイティブプラグインとして導入するには、チェックアウトをローカルマーケットプレイスに登録します。チェックアウトをマーケットプレイスのルートにする場合は、以下を `.agents/plugins/marketplace.json` に保存します。

```json
{
  "name": "nstack-local",
  "plugins": [{
    "name": "nstack",
    "source": {"source": "local", "path": "./"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity"
  }]
}
```

```sh
codex plugin marketplace add /ローカルマーケットプレイスの絶対パス
codex plugin add nstack@nstack-local
```

プラグインのスキルには名前空間が付きます。スキル選択画面で `$nstack:natori-mode` や `$nstack:setup-nstack` を選びます。カスタムエージェント TOML は[クイックスタート](../README.ja.md)の手順で別途配置します。
