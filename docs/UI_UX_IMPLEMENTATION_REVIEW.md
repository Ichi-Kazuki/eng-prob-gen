# UI/UX Review

- レビュー日時: 2026-08-24
- 対象: `itp-prob-gen` プロジェクト全体（branch `codex` / HEAD `2d840ea` / working tree clean）
- 依頼内容: 「シニアエンジニアのエージェントのみを使いプロジェクト全体をレビューしてください」

## 1. Review Scope and Mode

**モード: Implementation Review（実装レビュー）**

対象はリポジトリ全体。Python 約13,000行、git管理下1,316ファイル（うち実プロジェクトコード59ファイル）。

**重要な前提: 本リポジトリにはUI層が存在しない。**
`package.json` / HTML / CSS / React・Vue等のフロントエンド資産はなく、`docs/UI_UX_PLAN.md` も存在しない。実体は、TOEFL ITP文法問題（Structure Part A / Written Expression Part B）をSpec駆動で
`Generator → Solver（blind）→ Reviewer` の多段パイプラインにより生成・審査・検証する、LLMサブエージェント＋Pythonドライバのシステムである。

したがって本レビューは、UI/UX観点を「該当なし」とし、シニアエンジニア観点（アーキテクチャ整合性・保守性・堅牢性・テスト・再現性・リポジトリ衛生）に振り替えて実施した。

**視覚設計 / レスポンシブ / アクセシビリティ: 該当なし（UI層が存在しない）。**

**起動エージェント（依頼により1体のみ）:**

| エージェント | 状態 |
|---|---|
| `senior-ui-engineer-reviewer` | 実行済み（初回はレポート未出力のため1回再実行し、完了） |
| `ui-ux-designer-reviewer` | **意図的に未起動**（ユーザー指示による。かつUI層不在で適用対象なし） |

## 2. Executive Verdict

**Approve with changes**

パイプラインの中核設計はLLM多段システムとして水準が高く、設計意図とコードが一貫している。既存19テストは全て通り、受け入れテストも18/18 PASS。
ただし**公開前に潰すべき実証済みの穴が1件（High）** ある。コミットされたJSON Schemaが実行系から一度も読まれておらず、実際のゲートと乖離しているため、必須項目を欠落させたitemが検証を素通りする。

| 区分 | 件数 |
|---|---|
| Blocker | 0 |
| High | 2 |
| Medium | 5 |
| Low | 3 |

## 3. Verified Strengths

いずれも実際にファイルを読み、または実行して確認した事実である。

1. **オーケストレータの「自ら判断しない」設計がコードで守られている。**
   `orchestrator/scripts/orchestrator.py:1-23` の宣言（"NO TOEFL grammar judgement of its own" / 各エージェント自身の `validate_output.py` へシェルアウトする）は、`orchestrator.py:216`（`subprocess.run([sys.executable, script_path, tmp_path])`）と `:249` で実装されている。スキーマ検証もブラインド化も自前再実装していない。

2. **システム障害とコンテンツ不良が型レベルで分離されている。**
   `orchestrator.py:207/223/237/256/259/266` が `SystemCallError`（スクリプト不在・起動失敗・JSON不正）を送出し、`:227` の `ok = proc.returncode == 0` とは別扱い。Stateも `GENERATION_FAILED` / `VALIDATION_FAILED` に分離（`orchestrator.py:78-79`）。

3. **Solver入力のブラインド化が二重防御になっている。**
   `create_solver_input.py` の allowlist に加え、`orchestrator.py:270-280` の `leakage_guard()` が**厳格allowlist**（`actual - allowlist` と `allowlist - actual` の双方向）で再検査。デノリストではないため、未知のフィールド名による漏洩も止まる。実測 `blinded_keys=['item_id','options','section','stem'] problems=[]`。

4. **Generator再生成フィードバックが情報遮断されている。**
   `orchestrator.py:283-292` の `build_generator_feedback()` は `item_id / issues / revision_requirements` のみを返し、`independent_answer` / `verdict` / `checks` を渡さない。この種のパイプラインで最も壊れやすい「答えの逆流」を構造的に防いでいる。

5. **encoding指定の規律が高く、Windows/cp932事故への耐性がある。**
   AST走査で file-I/O 呼び出し **116件中114件が `encoding="utf-8"` 明示**。未指定の2件は `PIL.Image.open()` のバイナリ読込で実害なし。実行環境は `locale.getpreferredencoding()=cp932` / `sys.flags.utf8_mode=0` であり、意図的な規律と判断できる。

6. **パス解決がcwd非依存。** `orchestrator.py:67-68` の `REPO_ROOT = Path(__file__).resolve().parents[2]` をはじめ、各スクリプトが `Path(__file__)` 基準。どのディレクトリから起動しても動く。

7. **受け入れテストに副作用フリーモードが実装されている。**
   `run_acceptance_tests.py:145-155` が `output_dir` 指定時に `config["paths"]["manual_review_queue"]` を差し替え、理由をコメントで明記。同規約が `analysis/we_v2/run_regression_contract.py:275`、`run_smoke_acceptance.py:160`、`run_p0_hardening_regression.py:169` にも横断適用されている。実行して18/18 PASS、かつ作業ツリーがcleanのままであることを確認。

8. **スキーマが「実行時に強制されない」ことを自ら明記している。**
   `orchestrator/schemas/accepted_item.schema.json:5` に "it is not (yet) enforced by a JSON Schema library at runtime" とある。配置は誤解を招くが、ドキュメントとしての誠実さは評価できる。

9. **テストの命題設計が良質。**
   `tests/test_integrity.py` の `test_deletion_between_two_different_marked_spans_is_ambiguous`、`test_unclassified_spans_are_reported_not_dropped`、`test_old_conclusion_reports_previous_run_not_current_cohort` は、いずれもfail-openを潰す方向の境界条件を突いている。

## 4. Consolidated Findings

### Blocker

なし。build不能・主要機能不能・公開不可レベルの問題は確認されなかった。

### High

#### [High] コミット済みJSON Schemaが実行されず、実ゲートと乖離している
- 視点: Engineer
- 対象: `agents/toefl_itp_grammar_generator/schema/structure_item.schema.json` ↔ `agents/toefl_itp_grammar_generator/scripts/validate_output.py:42-72`（他5エージェントも同様）
- 問題: 6つのエージェントスキーマのうち、`validate_output.py` がスキーマファイルを読み込むものは1つもない（v2 generatorのみ `validate_format.schema_errors` 経由で自スキーマを使用）。実ゲートはPythonでハードコードされた別実装であり、スキーマとの整合を保証する仕組みがない。
- 根拠: 全 `validate_output.py` に `.schema.json` の参照なし（generatorは `SPEC_JSON`＝taxonomyのみ参照、`validate_output.py:19`）。スキーマ `required` 12項目のうち `subtype` / `secondary_features` / `vocabulary_domain` / `answer_explanation` の4つは、バリデータのソース中に**文字列としてすら一度も現れない**。実証：この4項目を欠落させ未知キー `totally_unexpected_field` を混ぜたStructure itemを投入 → 実行ゲートは **exit 0「All items passed hard schema validation」**、一方スキーマ検証（`additionalProperties: false`）では**5件のエラー**。
- 影響: `orchestrator/config.json` の `generator_validate_script` が指すのはこのスクリプトであるため、スキーマ違反itemが `VALIDATION_FAILED` にならずパイプラインを通過する。下流の `build_accepted_item()` は `g["answer_explanation"]`（`orchestrator.py:582`）と `g["subtype"]`（`:587`）を直接添字アクセスしており、`orchestrator.py:641` の呼び出し箇所に try/except がない。結果、ACCEPTED到達後に未捕捉 `KeyError` でバッチ実行全体が異常終了する経路が存在する。
- 改善案: **依存追加なしで解決可能。** `validate_format.py:94` の `schema_errors()` は既に汎用のJSON Schemaサブセット実装で、各スキーマが使うキーワード（`type/enum/const/required/properties/additionalProperties/minLength/minimum/maximum/minItems/items`）を網羅している。これを共有モジュールへ切り出し、各 `validate_output.py` を「①自身の `schema/*.json` に対し `schema_errors()` を実行 → ②既存のハンドコード意味検査（taxonomy所属、footnote 1/2 の禁止値など）」の2段構成にする。ハンドコード部分はスキーマで表現できない検査として残す。
  - 注: `solver_output.schema.json` と `reviewer_output.schema.json` は `allOf`/`if`/`then` を使用しており `schema_errors()` 未対応。この2つのみ条件分岐部分はハンドコードで残す（solver側は `validate_output.py:69-78` が if/then 相当を正しく再現済みであることを確認済み）。
- 確認方法: 上記の欠落itemを各 `validate_output.py` に投入して exit 1 になること。加えて既存の全コミット済みアーティファクト（`analysis/pilot/pilot_accepted_items.json` 等）を新ゲートに通し、過去データが新基準を満たすか回帰確認する。

#### [High] Solver出力のリーク検査がデノリスト方式で、新規キー名を素通しする
- 視点: Engineer
- 対象: `agents/toefl_itp_grammar_solver/scripts/validate_output.py:82-99`
- 問題: Solver**入力**側の `leakage_guard()` が厳格allowlistであるのに対し、**出力**側は既知16キーのデノリストのみ。スキーマ側には `additionalProperties: false` があるが、上記Findingのとおり実行されない。
- 根拠: 実証。`correct_answer_leak_via_new_name` / `internal_chain_of_thought` / `debug_generator_target` を含むSolver出力を投入 → 実行バリデータは **exit 0**、スキーマ検証は `additional property ... is not allowed` を**3件**報告。
- 影響: ブラインド性はこのパイプラインの中核的な正当性根拠であり、`qa_audit` にはSolver出力がそのまま記録される。LLMが未知のキー名で内部推論やメタデータを吐いた場合、検出されずQA記録に混入する。入力側が守られているため実際の「答えの漏洩」リスクは限定的だが、防御の非対称性は設計上の穴。
- 改善案: `REQUIRED_TOP_KEYS ∪ {"suggested_correction"}` を allowlist とし、`set(item) - allowlist` を全てエラーにする（デノリストは説明的メッセージ用に残してよい）。
- 確認方法: 上記3キー混入ケースで exit 1 になること。既存の `analysis/**/solver*.json` 全件を通して誤検知が出ないこと。

### Medium

#### [Medium] `analysis/` の実行スクリプトがワンショット記録装置で、再実行すると成果物を破壊する
- 視点: Engineer
- 対象: `analysis/we_v2_validation/run_validation.py:72`、`analysis/we_v2_pilot/build_pilot_artifacts.py:44`、`analysis/we_v2_pilot/build_plan.py:17` ほか計10ファイル
- 問題: `RUN_ID = "we-v2-validation-20260824"` / `BATCH_ID = "we-v2-live-pilot-20260824"` がモジュール定数としてハードコードされ、CLI引数も出力先指定もない。実行するとコミット済みの同名JSONを上書きする。さらに `run_validation.py:1406` と `build_pilot_artifacts.py:325` は `datetime.now(timezone.utc)` を埋め込むため、同一入力でも出力が毎回変わる。
- 根拠: grepで確認。加えて `run_validation.py:103-104` などはモジュールトップレベルで `load_json()` と `sha256()`（プロンプトファイルのハッシュ）を実行しており、importしただけでファイルI/Oが走る。`.claude/agents/*.md` が1つでも欠けるとimport時点で落ちる。
- 影響: 「レビュー成果物」と「それを生成するコード」が同一ディレクトリに混在しているため、第三者が検証のつもりでスクリプトを起動すると証跡が消える。`orchestrator/scripts/` 側は `output_dir` 規約を確立しているのに、`analysis/` 側にはそれが適用されていない（一部を除く）。同一リポジトリ内での規約の不統一。
- 改善案: `run_acceptance_tests.py:145` と同じ `output_dir` 引数パターンを `analysis/*/run_*.py`・`build_*.py` に横展開。`RUN_ID` は argv または環境変数で上書き可能にし、デフォルトは現行値を維持して後方互換を保つ。トップレベルI/Oは `main()` 内か遅延ロードへ移す。
- 確認方法: `git status --short` がcleanのまま各スクリプトを `output_dir` 付きで実行できること。

#### [Medium] オーケストレータ本体（753行・意思決定の中核）に単体テストがない
- 視点: Engineer
- 対象: `orchestrator/scripts/orchestrator.py` 全体、`tests/`
- 問題: `tests/` の19テストが触るのは `analysis/we_v2_validation/integrity.py`、`run_integrity_reaudit.py`、`emit_output.py`、`validate_format.py`、`prepare_revision_outputs.py` のみ。`evaluate_consensus()` / `process_solver_stage()` / `build_accepted_item()` / `build_qa_audit()` は `tests/` から一度もimportされていない。
- 根拠: `tests/*.py` の import 文を確認（`sys.path.insert` 先は `analysis/we_v2_validation`、generator scripts、pilot、patch のみで、`orchestrator` を含まない）。
- 影響: 実質的な保護は `run_acceptance_tests.py`（18項目、全PASS確認済み）だが、これは `tests/` の外にあり `python -m unittest` では走らない。CI設定もないため、CI導入時に最も重要なテストが取りこぼされる。またフィクスチャ再生方式のためconsensusの分岐網羅は合成入力に頼っており、`build_accepted_item()` の欠損キー経路（High #1）は誰も踏んでいない。
- 改善案: `run_acceptance_tests.py` を廃止せず、`tests/test_orchestrator_acceptance.py` から `main(tmp_path)` を呼ぶ薄いラッパを1本追加してunittest配下に取り込む。加えて `build_accepted_item()` に対する欠損フィールドテストを追加。
- 確認方法: `python -m unittest discover` 相当のコマンド一発でacceptanceを含む全テストが走ること。

#### [Medium] パッケージ構成がなく、`sys.path.insert` と動的ロードで依存が結線されている
- 視点: Engineer
- 対象: `analysis/we_v2_validation/run_validation.py:59`、`analysis/we_v2/run_regression_contract.py:51`、`analysis/we_v2/run_smoke_acceptance.py:16`（`load_module()` の3重複）、および `sys.path.insert` 20箇所
- 問題: `__init__.py` がリポジトリ内に1つも存在せず、`pyproject.toml` もない。モジュール間参照は `sys.path.insert()` と `importlib.util.spec_from_file_location()` で行われている。
- 根拠: `find . -name "__init__.py"` の結果は0件。`load_module()` は3ファイルにAST完全一致でコピー、`load_items()` は4ファイルに完全一致で重複（同名関数は8ファイル）。実測で `python -m unittest discover -s tests` が `ImportError: Start directory is not importable` で失敗する。
- 影響: 実行自体はできるが、標準的なテスト収集コマンドが通らない。また `validate_output` という名前が6箇所に存在し、`sys.path` の順序次第で別物が読まれるリスクがある。
- 改善案: 大規模刷新は不要。`tests/__init__.py` の追加と、最小限の `pyproject.toml`（`[tool.pytest.ini_options] pythonpath = [...]` 等のツール設定のみ）で解消できる。`load_module` / `load_items` / `write_json` / `pct` は共有モジュール1本に集約する。
- 確認方法: `python -m unittest discover -s tests -t .` がImportErrorなしで19テストを収集すること。

#### [Medium] 依存関係の宣言とREADMEがなく、第三者による再実行手順が確立していない
- 視点: Engineer
- 対象: リポジトリルート（`README.md` / `requirements.txt` / `pyproject.toml` いずれも不在）
- 問題: 必要なPythonバージョンとサードパーティ依存が宣言されていない。`tmp/crop_image.py:19` と `tmp/underline_candidates.py:41` はPILを要求するが、その事実がどこにも書かれていない。
- 根拠: 実行環境は Python 3.14.7。`pytest` は未インストール（`python -m pytest` は `No module named pytest` で失敗）。
- 影響: パイプライン本体が標準ライブラリのみで動くことは大きな強みだが、それが意図的な設計制約か偶然かを外部から判別できず、将来の貢献者が安易に依存を追加する余地がある。
- 改善案: 短い `README.md`（実行順序＋「本体は標準ライブラリのみ」の明文化）と、開発用依存のみの `requirements-dev.txt` を追加。`orchestrator/TOEFL_ITP_GRAMMAR_PIPELINE.md` が実質のドキュメントとして機能しているため、READMEから導線を張れば足りる。
- 確認方法: クリーンな環境でREADME記載手順のみを実行し、acceptanceが18/18になること。

#### [Medium] `.gitignore` 不在により、ベンダーライブラリと生成物が1,316ファイル中1,119ファイルを占める
- 視点: Engineer
- 対象: `.analysis_tmp_deps/`（899ファイル）、`__pycache__/*.pyc`（134ファイル）、`tmp/`（86ファイル）
- 問題: PIL / cryptography / cffi / pdfminer / pypdf などのサードパーティパッケージ実体がgit管理下にある。`.pyd` / `.exe` / `.dll` などのバイナリが21ファイル含まれる。
- 根拠: `git ls-files` 集計の実測値。実プロジェクトコードは `agents`(29) + `orchestrator`(21) + `specs`(5) + `tests`(4) の**59ファイルのみ**。
- 影響: (a) 意味のあるレビュー対象がノイズに埋もれる。(b) `cryptography 50.0.0` などのバイナリ配布物をリポジトリに固定してしまい脆弱性追跡の対象になる。(c) クローン／CIチェックアウトのコスト。(d) `.pyc` はソース変更と非同期に古いバイトコードを持ち込みうる。
- 改善案: `.gitignore` に `__pycache__/`、`*.pyc`、`.analysis_tmp_deps/`、`.analysis_tmp_uv_cache/` を追加し、`git rm -r --cached` で追跡解除。`tmp/pdfs/*.png` はOCR中間生成物として同様に判断。ルート直下の孤立ファイル `itp_structure_item_specs_testB.json` は、後継とみられる `analysis/itp_structure_item_specs_testB_v2.json` との関係を明記するか削除する。
- 確認方法: `git ls-files | wc -l` が3桁前半になり、`git status --short` がcleanを保つこと。

### Low

#### [Low] ディレクトリ命名が世代を表現できておらず、対応関係が名前から読めない
- 視点: Engineer
- 対象: `analysis/pilot/`、`analysis/validation/`、`analysis/we_v2_pilot/`、`analysis/we_v2_validation/`、`analysis/we_v2_patch/`、`analysis/we_v2/`
- 問題: `pilot` と `we_v2_pilot` の関係（v1系/v2系）が名前から判別できず、`analysis/we_v2/` と `analysis/we_v2_pilot/` の粒度差も不明瞭。さらに `analysis/pilot/build_pilot_artifacts.py`（646行）と `analysis/we_v2_pilot/build_pilot_artifacts.py`（1117行）は**同名の別ファイル**。
- 根拠: ファイル一覧と `sys.path.insert` の混在（`run_patch.py:29/38/41` が3ディレクトリを同時に `sys.path` へ投入）。同名ファイルが `sys.path` 上に複数ある状態は順序依存の事故を招く。
- 影響: 保守時の誤読・誤編集リスク。実害は現時点で未確認。
- 改善案: `analysis/runs/v1-pilot/`、`analysis/runs/v2-pilot/` のように世代を明示し、スクリプトは `analysis/scripts/`、成果物は `analysis/runs/` へ分離する。次の大きな世代（v3）を作る前に実施するのが安価。
- 確認方法: 移動後に全acceptance / regressionが同一結果を返すこと。

#### [Low] `run_validation.py` が1,513行の単一責務過多モジュール
- 視点: Engineer
- 対象: `analysis/we_v2_validation/run_validation.py`
- 問題: 定数定義・spec読込・プロンプトハッシュ計算・検証実行・メトリクス集計・Markdownレポート描画（`render_report`、`:1505`）が1ファイルに同居。
- 根拠: 行数と、`:1136` 等にレポート本文の文字列リテラルが直接埋め込まれている点。
- 影響: 変更時の影響範囲が読みにくい。ただし当該スクリプトは `JUDGMENT_MODE = "contract_only_replay"` / `JUDGMENT_QUALITY_EVALUABLE = False`（`:80-81`）と自らの適用範囲を明示しており、記録装置としての性格を自認している点は評価できる。
- 改善案: 最低限 `render_report` 系をレポート専用モジュールへ分離する（`analysis/we_v2_pilot/write_pilot_report.py` という先例が既にある）。
- 確認方法: 分離後にレポート出力がバイト単位で一致すること。

#### [Low] レポート文字列の非ASCII文字がcp932標準出力へ流れる経路がある
- 視点: Engineer
- 対象: `analysis/we_v2_patch/run_patch.py:533-543`、`analysis/we_v2_pilot/write_pilot_report.py:17`
- 問題: 各種記号および日本語がソース中に存在する。ファイル出力は全て `encoding="utf-8"` で安全だが、`print()` 経由の場合 `sys.stdout.encoding` に依存する。
- 根拠: 実行環境の `sys.stdout.encoding` が `cp932` であることを確認。現在使用中の文字は全てcp932に収録されており、実害は確認されていない。
- 影響: 将来cp932未収録の記号や絵文字を追加した際に `UnicodeEncodeError` で落ちる潜在リスク。
- 改善案: 各エントリポイント冒頭で `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` を呼ぶ、または実行手順で `PYTHONUTF8=1` を指定する。
- 確認方法: `chcp 932` 環境で各スクリプトを実行し `UnicodeEncodeError` が出ないこと。

## 5. Designer Review Summary

**未実施。** ユーザーの明示的指示（「シニアエンジニアのエージェントのみを使い」）により `ui-ux-designer-reviewer` は起動していない。
またリポジトリにUI層・デザイン資産・画面仕様が存在しないため、デザイナー観点は適用対象がない。この視点の欠落によって見落とされたリスクは、本プロジェクトにおいては実質ゼロと判断する。

## 6. Senior Engineer Review Summary

`senior-ui-engineer-reviewer` が実装レビューを実施。初回実行では最終レポートを出力せずに終了したため、レビュー・プロトコルに従い1回だけ再実行し、完了した（追加調査なしで既得の知見からレポートを出力させた）。

得られた結論の要点:

- 中核設計（判断の非集中化、二重ブラインド、フィードバック遮断、障害の型分離）は「後付け」ではなくコードとコメントが一貫しており、水準が高い。
- 最大の問題はスキーマとバリデータの乖離であり、これは**実証済み**（欠落itemが exit 0 で通過）。しかも下流の直接添字アクセスにより `KeyError` クラッシュ経路につながる。
- 修正には**新規ライブラリを一切必要としない**。`validate_format.py:94` の `schema_errors()` が既存の依存フリー実装として使える。
- リポジトリ衛生（1,316ファイル中1,119がベンダー／生成物）は、レビュー可能性そのものを損なっている。

## 7. Conflicts and Trade-offs

デザイナー視点が不在のため、視点間の衝突は発生していない。エンジニア観点内でのトレードオフは以下。

1. **スキーマ実行化（High #1）vs 過去データの互換性**
   スキーマを実際のゲートに昇格させると、既にコミット済みのアーティファクトが新基準で不合格になる可能性がある。**推奨: 先に既存アーティファクト全件を新ゲートで回帰確認し、乖離があればスキーマ側の `required` を実態に合わせるか、データ側を移行するかを個別判断する。** 「スキーマを緩めて通す」という安易な解決は、Highの根本原因（実ゲートが緩い）をスキーマ側に転写するだけなので避けるべき。

2. **`analysis/` の `output_dir` 化（Medium #1）vs 既存アーティファクトの証跡性**
   `RUN_ID` を可変にすると、成果物のファイル名から実行日が読めなくなる懸念がある。**推奨: デフォルト値を現行のハードコード値のまま維持し、上書きは opt-in にする。** 後方互換を保ちつつ再実行の安全性を得られる。

3. **ディレクトリ再編（Low #1）vs 移行コスト**
   命名の乱立は実害が未確認であり、一方で `sys.path` に同名ファイルが並ぶ構造は事故の温床。**推奨: 今は着手せず、v3世代を作る直前に実施する。** その時点なら移行コストが最小になる。

## 8. Plan-to-Implementation Traceability

`docs/UI_UX_PLAN.md` は存在せず、UI計画書との対応関係は追跡対象なし。
代わりに、本プロジェクトにおける「計画→実装」に相当する `仕様 → エージェント定義 → スキーマ → バリデータ` のトレーサビリティを評価した。

| 層 | 実体 | 実装との結線 |
|---|---|---|
| 仕様（source of truth） | `specs/toefl_itp_grammar_spec.json` + `TOEFL_ITP_GRAMMAR_SPEC.md` | **未検証**（MD/JSON二重管理のdrift有無は未確認） |
| エージェント定義 | `agents/*/AGENTS.md`、`.claude/agents/*.md` | **未検証**（重複・乖離は未確認） |
| スキーマ | `agents/*/schema/*.json`、`orchestrator/schemas/*.json` | **結線されていない**（High #1・#2の根本原因。6ペア全てで `validator_loads_schema=False`） |
| 実行ゲート | `agents/*/scripts/validate_output.py` | ハードコード実装。スキーマとの整合保証なし |
| パイプライン制御 | `orchestrator/scripts/orchestrator.py` | `config.json` 経由でバリデータへ結線。**確認済み・良好** |
| 受け入れ検証 | `run_acceptance_tests.py` | 18/18 PASS。ただし `tests/` 配下ではない（Medium #2） |

**結論: 仕様→オーケストレータの結線は健全だが、スキーマ層が実装から切り離された「宣言だけの層」になっている。** これがHigh #1・#2の共通根本原因である。

## 9. Prioritized Action List

### 今すぐ直す（公開・次バッチ実行の前）

1. **各 `validate_output.py` に自身のスキーマ検証を前段として組み込む**（High #1）
   `validate_format.py:94` の `schema_errors()` を共有モジュール化し、6エージェント全てに適用。`solver` / `reviewer` の `allOf`/`if`/`then` 部分のみハンドコードを残す。
2. **Solver出力のリーク検査をallowlist方式へ変更**（High #2）
   `REQUIRED_TOP_KEYS ∪ {"suggested_correction"}` 以外の全キーをエラーに。
3. **`.gitignore` の追加と `git rm -r --cached` による追跡解除**（Medium #5）
   `__pycache__/`、`*.pyc`、`.analysis_tmp_deps/`、`.analysis_tmp_uv_cache/`。レビュー可能性の回復として先に済ませるのが安価。
4. **1〜2の修正後、既存の全コミット済みアーティファクトに対する回帰確認**
   新ゲートで過去データが不合格にならないこと。不合格が出た場合はトレードオフ #1 の方針で個別判断。

### 実装前に決める（設計判断が必要）

5. **スキーマとバリデータのどちらをsource of truthにするかを明文化する**
   High #1の修正方針そのものが、この判断に依存する。推奨はスキーマを正とし、バリデータは「スキーマで表現できない意味検査の追加層」と位置づけること。
6. **`specs/` のMD/JSON二重管理の役割分担を明記する**（未検証領域）
   どちらが正で、どちらが説明かを `README.md` またはspec冒頭に書く。同様に `agents/*/AGENTS.md` と `.claude/agents/*.md` の関係も。
7. **`.claude/scheduled_tasks.lock` によるスケジュール実行の有無を確認する**（未確認）
   自動実行が存在する場合、Medium #1（再実行で成果物を上書き）の緊急度が上がる。

### 次の改善（次イテレーション以降）

8. `analysis/*` へ `output_dir` 規約を横展開し、`RUN_ID` を上書き可能にする（Medium #1）
9. `tests/__init__.py` と最小限の `pyproject.toml` を追加し、`unittest discover` を通す（Medium #3）
10. `run_acceptance_tests.py` をunittest配下に取り込み、`build_accepted_item()` の欠損フィールドテストを追加（Medium #2）
11. `README.md` と `requirements-dev.txt` を追加（Medium #4）
12. `load_module` / `load_items` / `write_json` / `pct` の重複を共有モジュールへ集約（Medium #3関連）
13. `render_report` 系の分離（Low #2）、stdout の UTF-8 化（Low #3）
14. v3世代の着手前に `analysis/` のディレクトリ再編（Low #1）

## 10. Acceptance and Verification Checklist

修正完了時に以下が全て満たされること。

- [ ] 必須4項目（`subtype` / `secondary_features` / `vocabulary_domain` / `answer_explanation`）を欠落させ未知キーを混ぜたStructure itemが、`validate_output.py` で **exit 1** になる
- [ ] 未知キー3個を混入させたSolver出力が、`validate_output.py` で **exit 1** になる
- [ ] 既存の全コミット済みアーティファクト（`analysis/pilot/pilot_accepted_items.json` 等）が新ゲートを通過する（または不合格分の扱いが文書化されている）
- [ ] `python -m unittest tests.test_integrity tests.test_we_v2_contract_boundaries -v` が **19 tests OK**（現在達成済み・退行させないこと）
- [ ] `python orchestrator/scripts/run_acceptance_tests.py <output_dir>` が **18/18 passed, EXIT=0**（現在達成済み・退行させないこと）
- [ ] 上記実行後も `git status --short` が **clean**（副作用フリー性の維持）
- [ ] `python -m unittest discover -s tests -t .` が ImportError なしで全テストを収集する
- [ ] `git ls-files | wc -l` が3桁前半になり、`.pyd` / `.exe` / `.dll` が追跡対象に含まれない
- [ ] `README.md` 記載の手順のみで、クリーン環境からacceptanceが18/18になる

**参考: 本レビュー時点で実際に確認した実行結果**

| コマンド | 結果 |
|---|---|
| `git status --short` | clean（開始時・終了時とも） |
| `python --version` | 3.14.7 |
| `python -m pytest tests/ -q` | 失敗（環境要因: pytest未インストール） |
| `python -m unittest discover -s tests -t .` | 失敗（構成要因: `tests/__init__.py` 不在） |
| `python -m unittest tests.test_integrity tests.test_we_v2_contract_boundaries -v` | **Ran 19 tests — OK** |
| `python orchestrator/scripts/run_acceptance_tests.py <scratchpad>` | **18/18 passed, EXIT=0**、作業ツリーclean維持 |
| AST走査: file-I/Oのencoding | 116件中114件が明示。未指定2件はPILバイナリ |
| AST走査: 関数重複 | 完全一致 `load_items`×4、`load_module`×3、`state_tally`×2 |
| `pilot_driver.py` vs `validation_driver.py` 類似度 | 48.2% |
| スキーマ `required` とバリデータの突合（6ペア） | 6ペア全てで `validator_loads_schema=False` |
| `git ls-files` 集計 | 1,316ファイル（`.analysis_tmp_deps`=899, `__pycache__`=134, `tmp`=86, バイナリ=21、実コード=59） |
| `find -name __init__.py` | 0件 |

## 11. Assumptions and Unverified Areas

**未読（行数と入出力の形のみ確認、内部ロジックの正当性は未検証）**
- `analysis/we_format/build_we_format_analysis.py`（870行）
- `analysis/validation/build_validation_artifacts.py`（701行）
- `analysis/we_v2_patch/run_patch.py`（707行の大半）
- `analysis/we_v2_validation/run_integrity_reaudit.py`（709行の大半）
- `analysis/we_v2_pilot/build_pilot_artifacts.py`（1,117行の大半）

**未検証**
- `specs/TOEFL_ITP_GRAMMAR_SPEC.md` と `specs/toefl_itp_grammar_spec.json` の内容整合。「JSONが正でMDが説明」という構造が実際に守られているかは未確認。
- 各 `agents/*/AGENTS.md` と `.claude/agents/*.md` の重複・乖離。
- `.claude/scheduled_tasks.lock` の役割。スケジュール実行が存在するならMedium #1の影響度が上がる。

**推測にとどまる部分（実証していない）**
- High #1 の `KeyError` 経路は、`orchestrator.py:582` の直接添字アクセスと `:641` の try/except 不在からの論理的帰結であり、**実際にクラッシュさせる再現は行っていない**。ACCEPTED到達にはReviewer PASSとSolver一致が必要なため、実運用で踏む確率は評価していない。
- Low #3 の `UnicodeEncodeError` は潜在リスクの指摘であり、現行の文字集合では発生を確認していない。

**意図的に実行しなかったもの**
- `analysis/` 配下の各 `build_*.py` / `run_*.py`（`output_dir` 引数を持つ3本を除く）。成果物を上書きする恐れがあるため。

**本レビューの範囲外**
- 生成されたTOEFL問題そのものの言語的品質。`run_validation.py:81` が `JUDGMENT_QUALITY_EVALUABLE = False` と自認しているとおり、既存アーティファクトも契約検査のリプレイであって品質評価ではない。

## 12. Final Recommendation

**Approve with changes**

パイプラインの中核設計は、この種のLLM多段システムとして水準が高い。オーケストレータが自前で判断せず各エージェントのバリデータへシェルアウトする規律、Solver入力の厳格allowlistによる二重ブラインド、再生成フィードバックの情報遮断、システム障害とコンテンツ不良の型レベル分離、cp932環境下での116件中114件のencoding明示、そして受け入れテストの副作用フリーモード（実行して18/18 PASS・作業ツリーclean を実測）——いずれも「後から取ってつけた」ものではなく、コードとコメントが一貫している。既存19テストも全て通る。

一方で、**公開前に潰すべき穴が1つある。** コミットされた `agents/*/schema/*.json` は実行系から一度も読まれておらず、実際のゲートであるハードコードPythonと乖離している。必須4項目を欠落させ未知キーを混ぜたitemが exit 0 で通過することを実証した。これは単なる整理の問題ではなく、下流の `build_accepted_item()` が該当キーを直接添字アクセスしているため、未捕捉 `KeyError` でバッチが落ちる経路につながる。Solver出力側のリーク検査がデノリスト止まりである点も、入力側がallowlistで守られているだけに防御の非対称が際立つ。幸い `validate_format.py:94` に既存の依存フリーなスキーマ検証実装があるため、**新規ライブラリを追加せず**、これを共有モジュール化して各バリデータの前段に差し込むだけで解決できる。

High 2件の修正、および `.gitignore` 追加によるリポジトリ衛生の回復（1,316ファイル中1,119がベンダー／生成物）を条件に、承認する。Medium 群（`analysis/` の実行安全性・オーケストレータの単体テスト・パッケージ構成・README）は次のイテレーションで計画的に対応すれば十分であり、いずれも既にリポジトリ内に良い先例（`run_acceptance_tests.py` の `output_dir` 規約、`TOEFL_ITP_GRAMMAR_PIPELINE.md`）があるため、横展開で低コストに解消できる。

---

*本レビューではコード・仕様書を一切変更していない。本ドキュメントの新規作成のみ。*
