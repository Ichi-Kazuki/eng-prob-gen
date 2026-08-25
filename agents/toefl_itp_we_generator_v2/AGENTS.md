# TOEFL ITP Written Expression Generator v2.1

このディレクトリは、既存の `agents/toefl_itp_grammar_generator/` と完全に分離されたWE専用v2実装である。

- schema: `schema/written_expression_item_v2.schema.json`
- format config: `config/we_v2_format_config.json`
- deterministic validator: `scripts/validate_format.py`
- format planner / span selector: `scripts/format_planner.py`
- contract validator: `scripts/validate_output.py`

v2.1の構築順序は clean sentence → clean validation → one-error mutation → uniqueness audit →
format plan conformance → sentence全体からのcandidate span列挙 → geometry-aware span selection
→ deterministic format diagnostics で固定する。既存v1.1のfull-sentence partition outputを
入力テンプレートとして再利用しない。

## v2.1 format policy

- sentence target は `analysis/we_format/written_expression_format_official.json` の
  `items[].sentence_word_count` を empirical sampling する。固定20語、固定13語、または
  hand-tuned probabilityは使わない。target ± tolerance の plan range と clean realizationを
  deterministic に照合し、外れた文はpaddingせず再生成する。
- correct-span type は同じ Official artifact の
  `items[].correct_span_type` counts から毎回 derive する。`SINGLE_WORD` を中心にし、
  `SHORT_PHRASE` と `CLAUSE_OR_CLAUSE_LIKE` は少数とする。grammar上の最小natural locusが
  sampled typeと異なる場合はgrammar validityを優先し、spanを強制短縮・拡張しない。
- correct span は grammatical decisionに必要な最小local spanとする。1語で足りるerrorを
  3語phrase全体に広げない。
- distractorはcorrect spanの周辺から選ばず、sentence全体の1–4語candidateから選ぶ。
  1語・natural 2-word unitを優先し、必要なときだけ3–4語を使う。5+語はnormal planから
  除外し、例外はrationale付きで監査する。
- Official gapsをsourceにして A–B / B–C / C–D をsampleする。gap=0 はnormal candidate
  として選ばず、候補組合せのsoft scoreには total marked words、coverage、unmarked
  context、gaps、max span、correct-span type、answer positionを含める。bandsを通すための
  hard optimizerにはしない。
- span set選択後、emission前に sentence length、span lengths、coverage、unmarked context、
  gaps、correct-span typeを再計算する。plan conformance failureはacceptしない。spanだけで
  修正できる場合はgrammar locusを固定してreselectionし、sentence planが短い場合はclean
  sentence generationへ戻る。

## v2.1 scope boundary

`grammar generation logic unchanged, format planner + span-selection policy only`。
mutation templates、`tested_error_type` logic、grammar validity checks、one-error checks、
Reviewer / Solver / Orchestrator、Grammar Specification、JSON Schemaのfield meaning、Format
Specificationのobserved values、Format band thresholdsは変更しない。
