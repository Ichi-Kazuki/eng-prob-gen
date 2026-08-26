# TOEFL ITP Written Expression Generator v2.1.2

v2.1.2 is the current runtime implementation label. The JSON Schema and
output-field contract remain the v2.1 contract because this release is a
grammar-mutation-safety patch; it does not introduce a schema-version bump.

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

## v2.1.1 format policy (locked in v2.1.2)

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

## v2.1.2 grammar mutation safety

The v2.1.2 patch changes grammar mutation safety only.  Before emission, the
Generator must quarantine ambiguous noun-phrase-to-pronoun substitutions,
reject semantic-only degree changes such as `sufficiently X -> too X` and
`enough X -> too X`, and guard base-form-to-`-ing` parallel mutations against
supplementary/adverbial participial and reduced-modifier alternate parses.

Every mutation must pass the strong one-error invariant: grammatical clean
sentence, genuinely ungrammatical mutated sentence, exactly one grammatical
defect, defect inside the declared span, minimal repair, no plausible
alternate parse, and no semantic-only oddity.  The clean/error forms,
mutation type, minimal correction, and answer explanation must describe the
same direction and local defect.  Uncertainty is a reject/regenerate result.

Use `scripts/mutation_safety.py` for the deterministic template classes and
metadata audit.  Its targeted template catalog is explicitly classified as
`SAFE`, `NEEDS_GUARD`, or `QUARANTINE`.

## v2.1.2 scope boundary

The format planner and all v2.1.1 geometry policy remain unchanged.  The only
new runtime surface is the grammar mutation safety guard and its deterministic
metadata audit; the JSON Schema/output-field contract remains unchanged.
