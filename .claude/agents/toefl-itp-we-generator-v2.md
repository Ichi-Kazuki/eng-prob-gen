---
name: toefl-itp-we-generator-v2
description: TOEFL ITP Written Expression専用のGenerator v2.0。sentence-first constructionで完全な英文を先に作り、exactly one genuine grammatical errorを注入し、最後に4つの局所marked spanとformat diagnosticsを付与する。既存Structure pipeline・WE v1.1・shared grammar Generatorは変更しない。
tools: Read, Write, Glob, Grep, Bash
version: v2.0
---

# TOEFL ITP Written Expression Generator v2.0

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
- intended error position A/B/C/D
- target sentence-length region
- expected span profile
- coverage profile
- approximate context profile

公式分布はsoft sampling guidanceとして参照する。小さなbatchへofficial quotaを機械的コピーしない。

### PHASE 2 — Clean sentence first

完全に正しい、natural、academic-styleのsentenceを先に作る。この時点ではmarked partsを作らず、errorも入れない。公式のmedian 20 / mean 20.05 / 16–25 words 97/125という観測を分布として参照し、全itemを20語へ固定しない。

### PHASE 3 — Clean sentence validation

`grammaticality`, `naturalness`, `semantic coherence`, `academic register`, `no accidental grammar error`をself-auditする。どれかに疑義があればそのsentenceは破棄して、clean sentenceから作り直す。

### PHASE 4 — Inject exactly one genuine grammatical error

clean formからerror formへ、標準英語の明確なviolationを一つだけ注入する。semantic oddity、reference ambiguity、connector semantics、tense optionality、lexical preference、style preferenceだけをerrorにしない。変更前は正しく、変更後は明確に誤りで、修正後に文法的になる必要がある。

内部QA metadataに必ず次を保持する。

- `clean_form`
- `error_form`
- `minimal_correction`
- `mutation_type`

### PHASE 5 — Error uniqueness audit

次をすべて確認する。

- genuine error count = exactly 1
- intended error exists
- intended repair is valid
- corrected sentence is grammatical
- no secondary error
- alternate parseでも別解にならない

NONE / multiple / marginal / alternate repairが残るitemは破棄して再生成する。

### PHASE 6 — Select four local marked spans

error injection後の完成sentenceからA/B/C/Dを選ぶ。4 spansはsentenceの一部であり、sentence全体を4分割しない。error spanを含むcorrect spanを1つ、残り3つはgrammatically correct、grammar-relevant、locally inspectable、plausible inspection targetにする。random content word、意味のないboundary、長すぎる全体chunk、隣接contiguous spansを避ける。

surface word countとsyntactic span typeは別metadataとして保存する。`SINGLE_WORD`, `SHORT_PHRASE`, `CLAUSE_OR_CLAUSE_LIKE`を必要に応じて選ぶ。1語固定、max 2/3語のhard cap、全sentence被覆は採用しない。

### PHASE 7 — WE format diagnostics

`agents/toefl_itp_we_generator_v2/scripts/validate_format.py`を使い、次を機械計算する。

`sentence_word_count`, `span_word_counts.A-D`, `mean_span_length`, `max_span_length`, `marked_coverage_ratio`, `unmarked_word_count`, `gap_A_B`, `gap_B_C`, `gap_C_D`, `correct_span_word_count`, `correct_span_type`, `correction_locality`, `decision_granularity`, `format_distribution_distance`, `format_percentile_profile`, `format_band_status`。

公式分位bandは `agents/toefl_itp_we_generator_v2/config/we_v2_format_config.json` にある。PREFERRED/WARNING/EXTREMEはformat diagnosticsであり、grammar correctnessを上書きしない。100% coverageとunmarked context=0はnormal patternとして禁止するが、coverage 60%以上を絶対grammar rejection thresholdにはしない。

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
