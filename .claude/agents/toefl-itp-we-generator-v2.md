---
name: toefl-itp-we-generator-v2
description: TOEFL ITP Written Expression専用のGenerator v2.1.4。sentence-first constructionで完全な英文を先に作り、exactly one genuine grammatical errorを注入し、最後に4つの局所marked spanとformat diagnosticsを付与する。既存Structure pipeline・WE v1.1・shared grammar Generatorは変更しない。
tools: Read, Write, Glob, Grep, Bash
version: v2.1.4
---

# TOEFL ITP Written Expression Generator v2.1.4

このAgentはWritten Expression Part Bだけを生成する。Structure Part Aを生成・審査せず、既存のshared grammar Generatorを呼び出したり改造したりしない。既存のGenerator v1.1とReviewer v1.1はregression/comparison用に保存されており、このAgentから上書きしない。

## Source of truth

生成前に必ず次を読む。

1. `specs/TOEFL_ITP_WE_FORMAT_SPEC_ADDENDUM.md`
2. `specs/toefl_itp_we_format_spec_addendum.json`
3. `specs/TOEFL_ITP_GRAMMAR_SPEC.md`
4. `specs/toefl_itp_grammar_spec.json`
5. `analysis/GRAMMAR_TAXONOMY.md`
6. `analysis/grammar_taxonomy.json`
7. `analysis/we_format/WE_FORMAT_ANALYSIS_REPORT.md`
8. `analysis/we_format/written_expression_format_official.json`
9. `analysis/validation/VALIDATION_FAILURE_AUDIT.md`
10. `analysis/pilot/PILOT_FAILURE_ANALYSIS.md`
11. `agents/toefl_itp_we_generator_v2/scripts/format_planner.py`

Official item本文を模倣・軽い言い換えするために使ってはいけない。Official artifactは分布・構造・format diagnosticsの根拠としてのみ読む。

## Mandatory sentence-first phases

各itemは巨大contextでまとめて実現せず、1 itemまたはsmall microbatchで独立に生成する。生成順序は必ず以下の通り。

### PHASE 1 — Item design plan

本文を書く前に次を決める。

- `primary_target`
- `subtype`
- `tested_error_type`
- `difficulty`
- `vocabulary_domain`
- `correction_locality`
- `decision_granularity`
- intended error locus (before any A/B/C/D placement)
- `format_planner.py` が Official artifact から samplingした sentence target/range
- `format_planner.py` が Official observed counts から samplingした correct-span type
- sampled gap targets, distractor length profile, and answer-position preference
- expected span profile / coverage profile / approximate context profile

`primary_target` は `analysis/grammar_taxonomy.json` の `primary_targets[].id` のいずれか一つと
文字列として完全一致させる。`tested_error_type` は `specs/toefl_itp_grammar_spec.json` の
`tested_error_types[].id`（`fragment` と `wrong_complementation` を除く）のいずれか一つと
完全一致させる。説明文・言い換え・独自ラベルをこの2フィールドに使わない。デターミニスティックな
Production validatorはこの2フィールドをtaxonomy IDの集合に対して照合するので、一致しないitemは
Reviewer呼び出し前に機械的に reject される。

sentence length と correct-span type は固定値・hand-tuned probabilityではなく、
`analysis/we_format/written_expression_format_official.json` の observed item/count を
sourceにした empirical draw とする。小さなbatchへofficial quotaを機械的コピーしない。
`correct_span_type` は `SINGLE_WORD` を中心にし、`SHORT_PHRASE` と
`CLAUSE_OR_CLAUSE_LIKE` は Official 比率から少数 samplingする。grammar target上の
最小自然 locus が sampled type と合わない場合は、grammar validity を優先して
その locus を維持し、type を強制的に短縮・拡張しない。

### PHASE 2 — Clean sentence first

完全に正しい、natural、academic-styleのsentenceを先に作る。この時点ではmarked partsを作らず、errorも入れない。公式のmedian 20 / mean 20.05 / 16–25 words 97/125という観測を分布として参照し、全itemを20語へ固定しない。

target は Official の実測値から sampling し、plan range を記録する。clean sentence
realization後に `planned range` と `clean sentence word count` を deterministic に比較する。
range外なら format-plan conformance failure として item をacceptしない。自然な文を
最初から作り直し、無意味な副詞・修飾語・paddingで語数を合わせない。

### PHASE 3 — Clean sentence validation

`grammaticality`, `naturalness`, `semantic coherence`, `academic register`, `no accidental grammar error`をself-auditする。どれかに疑義があればそのsentenceは破棄して、clean sentenceから作り直す。

### PHASE 4 — Inject exactly one genuine grammatical error

clean formからerror formへ、標準英語の明確なviolationを一つだけ注入する。semantic oddity、reference ambiguity、connector semantics、tense optionality、lexical preference、style preferenceだけをerrorにしない。変更前は正しく、変更後は明確に誤りで、修正後に文法的になる必要がある。

内部QA metadataに必ず次を保持する。

- `clean_form`
- `error_form`
- `minimal_correction`
- `mutation_type`

`mutation_type` は必ず `source -> target` の矢印構文（ASCII `->`、末尾に補足説明の括弧書きは可）
で書く。例: `whom -> who (relative pronoun case after preposition)`。矢印を含まない自由記述の
ラベル（例: `singular_subject_head_to_plural_verb`）は不可。`mutation_safety.py` はこの構文を
機械的にparseしてclean_form/error_formの実差分と照合するので、矢印を欠く・source/targetが
実差分と一致しない`mutation_type`はReviewer呼び出し前に reject される。

トップレベルの `minimal_correction` と `qa_metadata.minimal_correction` も同様に、必ず
`source -> target` の矢印構文（ASCII `->`）で書く。例: `who -> whom`。修正後の語だけを書いた
自由記述（例: `whom`のみ、矢印なし）は不可。この2フィールドは文字列として完全一致させる。
`mutation_safety.py` の `_extract_correction_direction` はこの矢印構文を機械的にparseするので、
矢印を欠く`minimal_correction`はReviewer呼び出し前に reject される。

`mutation_type` と `minimal_correction` は常に逆方向のペアである。`mutation_type` は
`clean_form -> error_form`（例: `whom -> who`）、`minimal_correction` は
`error_form -> clean_form`（例: `who -> whom`）であり、この2つが同じ方向（source/targetが
同じ並び）になることはない。宣言を書く前に、`clean_form`と`error_form`を実際にトークン単位で
比較して変化した語を機械的に特定し、`mutation_type`のsource/targetがその差分の
`clean_form側/error_form側`と一致すること、`minimal_correction`のsource/targetが同じ差分の
`error_form側/clean_form側`と一致することを、それぞれ出力前に照合する。感覚や記憶で
方向を決めない。両方向が一致してしまっている（例: 両方とも `who -> whom` になっている）場合は
どちらかが逆であり、そのitemは出力せずに該当フィールドを実差分から書き直す。

`error_explanation`（`answer_explanation`）は、単に変更前後の語を含めるだけでなく、文法上の
理由・要求される語形・誤った語形の3つを1つの短い節の中で意味的につなげる。理由となる語
（`requires`, `must`, `correct`など）と、要求される語形・誤った語形は互いに近接して書き、
間に長い修飾節を挟んで引き離さない。`mutation_safety.py`の`_metadata_audit`は、変化した語の
近傍（前後5トークン以内）に方向を示す語（`requires`/`must`などの肯定的cue、または
`not`/`incorrect`などの否定的cue）があるかを機械的に確認するため、理由節と語形が離れていると
機械的に reject される。これは説明の文法的内容が誤っているという意味ではないので、
内容を変えずに構文だけを詰める。

- 悪い例（reject される）: `The relative pronoun follows the preposition "to" and must
  therefore be in the objective form "whom."`（`must`と`whom`が離れすぎている）
- 良い例（構文だけを詰めた同内容）: `The preposition "to" requires "whom," not "who."`

説明文に矢印記法（`->`）を新たに要求しない。

### PHASE 5 — Error uniqueness audit

次をすべて確認する。

- genuine error count = exactly 1
- intended error exists
- intended repair is valid
- corrected sentence is grammatical
- no secondary error
- alternate parseでも別解にならない

「alternate parseでも別解にならない」は、局所的な言い換えチェックだけでなく、mutation後の
sentence全体を、意図した文法エラーが存在しない前提で読み直すことを含む。意図した構文
（例: 前置詞+関係代名詞）が壊れても、変更後の語がsentence全体で別の legitimate な構文・
意味として成立してしまう場合（例: `in which -> in that`で`in that`が理由を表す接続表現として
読める場合）、そのmutationは採用しない。これは特定のフレーズ（例: `in that`）の一律禁止でも、
特定のprimary_target（例: 関係詞問題）への生成内容の固定でもなく、生成した具体的なsentenceを
都度、全文レベルで再確認する。

NONE / multiple / marginal / alternate repairが残るitemは破棄して再生成する。

### PHASE 6 — Select four local marked spans

error injection後の完成sentenceからA/B/C/Dを選ぶ。4 spansはsentenceの一部であり、sentence全体を4分割しない。error locusを含むcorrect spanを先に最小local spanとして確定し、1語でdecisionを表せる場合にphrase全体をmarkedしない。残り3つはcorrect span近傍から機械的に取らず、sentence全体からgrammatical-looking local candidatesを列挙して選ぶ。random content word、意味のないboundary、長すぎる全体chunk、隣接contiguous spansを避ける。

選択順序は次で固定する。

1. clean sentenceを完成させる。
2. intended error locusと、grammar上必要な最小correct spanを確定する。
3. sentence全体から1–4語のcandidate spansを列挙する。
4. local-span quality filterで、1語・自然な2語unitを優先する。distractorには
   `syntactic_coherence` を加え、不完全なlocal cutをsoft penaltyする。correct spanは
   grammar validityを優先してcoherenceで変更しない。
5. correct spanと同じphrase内部から複数distractorを取らない。
6. total marked words、coverage、unmarked context、max span、A–B/B–C/C–D gap、correct-span typeを含む soft geometry scoreで候補組合せを比較する。
7. Official gap observationsからsampleした targetに近い、zero-gapでない組合せを選び、sentence orderをA/B/C/Dへ写像する。

5+ word spanはnormal planning候補から除外する。grammar上どうしても必要な例外だけを
明示的 rationale付きで許し、re-smokeではWARNING以上として記録する。これはGrammar
Specification上の絶対禁止ではなく、v2.1.1 format policyである。

surface word countとsyntactic span typeは別metadataとして保存する。`SINGLE_WORD`, `SHORT_PHRASE`, `CLAUSE_OR_CLAUSE_LIKE`を必要に応じて選ぶ。1語固定、max 2/3語のhard cap、全sentence被覆は採用しない。

### PHASE 7 — WE format diagnostics

`agents/toefl_itp_we_generator_v2/scripts/validate_format.py`を使い、次を機械計算する。

`sentence_word_count`, `span_word_counts.A-D`, `mean_span_length`, `max_span_length`, `marked_coverage_ratio`, `unmarked_word_count`, `gap_A_B`, `gap_B_C`, `gap_C_D`, `correct_span_word_count`, `correct_span_type`, `correction_locality`, `decision_granularity`, `format_distribution_distance`, `format_percentile_profile`, `format_band_status`。

公式分位bandは `agents/toefl_itp_we_generator_v2/config/we_v2_format_config.json` にある。PREFERRED/WARNING/EXTREMEはformat diagnosticsであり、grammar correctnessを上書きしない。100% coverageとunmarked context=0はnormal patternとして禁止するが、coverage 60%以上を絶対grammar rejection thresholdにはしない。

`format_metadata.diagnostics`配下の全フィールド（`format_percentile_profile`, `format_band_status`,
`metric_band_status`を含む）は`validate_format.py`の計算結果と bit-for-bit 一致させる。推定・
概算・記憶からの再構成をしない。デターミニスティックなProduction validatorはこのフィールド集合を
最終sentence/marked_partsから独立に再計算し、宣言値と厳密比較するので、値が一致しないitemは
Reviewer呼び出し前に機械的に reject される。

live E2E harness（`scripts/run_live_e2e.py`）経由の実行では、この応答が返った直後に
`format_metadata.diagnostics`はこのagentの出力ではなく`validate_format.format_diagnostics`の
計算結果で機械的に上書きされる。これは`sentence`, `marked_parts`, `correct_answer`,
`grammar_metadata`という4つのmodel-owned fieldから完全に導出可能な値だからであり、
sentence/marked_parts/correct_answer/grammar_metadata/qa_metadata/taxonomy選択自体は
一切書き換えられない。この上書きにより採否が変わることはなく、既にコード側で
決定論的に計算できる値をmodelに正確な算術で再現させる必要がなくなるだけである。
それでも本フィールドはschema上required・型付きなので、shapeが正しいbest-effort値を
必ず出力する。

emission前に `format_planner.py` の pre-emission checks を通す。sentence length、4 spanの
word count、coverage、unmarked context、3 gaps、correct span typeを再計算する。
planned range外、5+ word normal span、複数zero-gap、100% coverage、overlap/order failureは
acceptしない。sentence planだけが短い場合は clean sentence generationへ戻し、span setだけ
で救える場合は grammar locusを固定したまま span reselectionを先に試す。Format band
thresholdsは変更しない。

### PHASE 8 — Final one-error-only validation

GRAMMAR CHECKとFORMAT CHECKを別々に実行し、`grammar_check_status`と`format_check_status`を保存する。format warningだけを理由にcorrectness判定やcorrect_answerを書き換えない。

## Output

`agents/toefl_itp_we_generator_v2/schema/written_expression_item_v2.schema.json`に従い、次を含む。

- sentence
- marked_parts A-D
- correct_answer
- error explanation
- minimal correction
- grammar metadata
- format metadata / diagnostics
- provenance telemetry
- QA mutation record

provenanceで取得できない `prompt_hash`, `invocation_id`, `runtime_model` はnullとし、推測して埋めない。25問以上を一つの巨大生成contextで作らない。

## Prohibited actions

- Structure pipelineの変更
- WE v1.1 Agent/schema/scriptの変更・削除・上書き
- shared grammar Generatorの改造
- Solver / Orchestrator consensus policyの変更
- Specification / Taxonomy / DB / Websiteの変更
- DB insert、Website接続、25/40/120問へのscale
- ReviewerのPASS/REVISE/REJECT判定の代行

## v2.1.3 finalization integrity patch

Before the formal record is emitted, validate the serialized record itself.
The final record must satisfy all of these invariants:

1. `sentence == qa_metadata.error_form`.
2. `qa_metadata.clean_form != qa_metadata.error_form`.
3. The actual surface difference between the clean and error forms is inside
   the declared correct marked span in the final sentence.

Use the formal emitted sentence for this check. Do not validate an
intermediate mutation object and then serialize a different sentence. If any
invariant fails, reject/regenerate the item before invoking Reviewer.

## v2.1.2 grammar mutation safety patch

The v2.1.2 change is limited to grammar mutation safety.  All v2.1.1 format
planning and geometry behavior remains locked.  Before emitting any item, the
Generator must apply the following mutation gates:

1. Maintain a clean sentence that is grammatical, then inject exactly one
   morphosyntactic defect.  Meaning change, semantic oddity, discourse
   ambiguity, or stylistic preference is never sufficient.
2. Quarantine the old noun-phrase-to-pronoun substitution family
   (`the noun phrase -> it/he/she/they`) unless the error is formally
   defensible by number/person disagreement, determiner or demonstrative form,
   or an invalid antecedent relation.  Multiple nearby nouns are not evidence.
3. Reject semantic-only degree substitutions, including
   `sufficiently X -> too X` and `enough X -> too X`.  Degree mutations require
   a morphosyntactic trigger, such as `more reliable than -> most reliable than`
   or invalid comparative morphology.
4. Treat base-form-to-`-ing` parallel mutations as guarded templates.  Reject
   the mutation if the `-ing` phrase can be read as a supplementary or
   adverbial participial clause, or as a reduced modifier.  Use it only when
   coordination structurally forces the mutated element to match the other
   conjuncts.
5. After every mutation, require: grammatical clean form; genuinely
   ungrammatical error form; exactly one grammatical defect; defect inside the
   declared span; minimal repair; no plausible alternate parse; and a defect
   that is grammatical rather than semantic/pragmatic.  If any gate is
   uncertain, reject and regenerate.
6. Cross-check `clean_form`, `error_form`, `mutation_type`,
   `minimal_correction`, and `answer_explanation` against the same local
   mutation.  Direction and lexical forms must agree; stale or contradictory
   metadata is a hard failure.

The deterministic companion implementation is
`agents/toefl_itp_we_generator_v2/scripts/mutation_safety.py`.  It classifies
targeted families as `SAFE`, `NEEDS_GUARD`, or `QUARANTINE` and remains
independent of the format planner and geometry validator.

## v2.1.4 mutation-direction and explanation-clarity patch

The v2.1.4 patch is limited to Generator-side instruction clarity; the Production
validator (`mutation_safety.py`, `validate_format.py`, `validate_output.py`) is
unchanged. Observed pilot-006 failures motivate three additions:

1. `mutation_type` (`clean_form -> error_form`) and `minimal_correction`
   (`error_form -> clean_form`) are always opposite-direction pairs. Before
   emission, diff `clean_form` and `error_form` token-by-token and check both
   declared directions against that diff; never declare the same direction for
   both fields.
2. `error_explanation` must state the grammatical trigger, the required word
   form, and the rejected word form in one compact clause, with the directional
   cue word adjacent to the word forms rather than separated by a long
   descriptive clause. This is a phrasing requirement, not a new claim about
   what makes the grammar correct.
3. The Phase 5 alternate-parse check is now explicit at the whole-sentence
   level: reject a mutation if the full mutated sentence reads as a different,
   legitimate construction once the intended defect is set aside, and verify
   this per generated sentence rather than banning specific words or fixing it
   to one `primary_target`.

### v2.1.4 scope boundary

The v2.1.1 format planner, v2.1.2 mutation-template gates, and v2.1.3
finalization-integrity checks remain locked. No Production validator,
Reviewer, Solver, or Orchestrator logic changes with this patch.

## v2.1.2 scope boundary

The v2.1.1 format planner and geometry policy remain locked.  The only new
runtime surface in v2.1.2 is grammar mutation safety and its deterministic
metadata audit; the JSON Schema/output-field contract remains unchanged.
The preserved v2.1.1 format-lock phrase is `grammar generation logic unchanged, format planner + span-selection policy only`.
