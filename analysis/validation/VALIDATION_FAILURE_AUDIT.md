# TOEFL ITP Grammar Pipeline v1.1 — Validation Failure Audit

作成日: 2026-08-24  
対象: Validation 120問 / Batch 1–3  
制約: 本成果物は分析とHuman Calibration準備のみ。Generator prompt、Reviewer prompt、Solver、Orchestrator consensus policy、Specification、Taxonomy、DB、Webサイトは変更していない。

## 1. 結論

JSON/provenanceを独立に再集計した結果、最終状態は **AUTO_ACCEPTED 83 / MANUAL_REVIEW 5 / DISCARDED 2 / REJECTED 30 = 120** で整合した。

最大の異常はBatch 2で、40問中10問しかAUTO_ACCEPTされず、Batch 2のWritten Expression 25問は全件がReviewer round1 REJECTとなった。25件は「誤りを含まないclean sentence」であり、主因はReviewerの過剰な厳しさではなく、Generatorのbatch/section単位の生成劣化またはcontext driftと推定する。Batch 2のStructure 2件はanswer key、3件はmanual routingであり、Batch 2の全失敗が同じ文法targetの難しさによるものではない。

一方、30 REJECTのうち **25件はREJECT妥当、5件は局所修正で救済できる可能性が高くREVISE相当** と独立評価した。標準英語として利用可能なのにREJECTされたと判断する明確なReviewer over-rejectionは0件である。

現時点の推奨は **F. Prompt変更前にHuman Calibration必須**。Calibration前にv1.2のpromptやthresholdを変更しない。

## 2. Source of truthと方法

最優先したのは `validation_provenance.json`、`validation_metrics.json`、`validation_initial_items.json`、`validation_failure_items.json`、`validation_manual_review.json`、`validation_batch_plans.json`、`human_review_sample.json`。Pilot、Agent、Specification、Taxonomyは比較・解釈に使用した。

再計算ではReportの数値を転記せず、以下を`validation_provenance.json`の120 itemから独立に数えた。

- final `state`
- round1のreview history
- last Reviewer verdict
- Solver answer / confidence
- Orchestrator consensus flag
- batch/section/slot metadata

なお、provenanceにはAgent invocation IDやcontext-window ID、機械的に構文解析済みのclause countは保存されていない。そのため、Batch 2のinvocation/context共有は「確認不能」と明示し、文長はsurface word count、clause countはbatch-plan targetとして扱った。

## 3. 完全reconciliation

### Final state

| 項目 | 独立再計算 | 要求値 | 判定 |
|---|---|---|---|
| Initial candidates | 120 | 120 | PASS |
| AUTO_ACCEPTED | 83 | 83 | PASS |
| MANUAL_REVIEW | 5 | 5 | PASS |
| DISCARDED | 2 | 2 | PASS |
| REJECTED | 30 | 30 | PASS |
| Equation | 83 + 5 + 2 + 30 = 120 | 83 + 5 + 2 + 30 = 120 | PASS |

### Reviewer / Solver

| 指標 | 独立再計算 | 要求値 |
|---|---|---|
| Reviewer round1 PASS | 80 | 80 |
| Reviewer round1 REVISE | 10 | 10 |
| Reviewer round1 REJECT | 30 | 30 |
| Reviewer eventual PASS | 89 | 89 |
| Solver reached | 89 | 89 |
| Solver consensus | 83 | 83 |
| Solver A-D disagreement | 2 | 2 |
| Solver AMBIGUOUS | 3 | 3 |
| Solver NONE | 1 | 1 |
| Solver LOW confidence | 1 | 1 |

## 4. 37 non-AUTO_ACCEPTの完全分類

全37件をfinal stateとprimary reasonで1件ずつ分類した。`classification`はAI独立評価であり、Human Calibrationで確定する。

| item_id | batch | section | final | target | difficulty | primary reason | independent classification | root cause |
|---|---|---|---|---|---|---|---|---|
| batch1-we-007 | batch1 | Written Expression | MANUAL_REVIEW | RELATIVE_CLAUSES | EASY | metadata_mismatch | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch1-we-013 | batch1 | Written Expression | DISCARDED | REFERENCE_AND_DETERMINERS | EASY | reference_resolution_dependency | LIKELY_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch1-we-024 | batch1 | Written Expression | MANUAL_REVIEW | REFERENCE_AND_DETERMINERS | MEDIUM | metadata_mismatch | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-struct-003 | batch2 | Structure | MANUAL_REVIEW | RELATIVE_CLAUSES | EASY | solver_ambiguous | SPEC_OR_TAXONOMY_EDGE_CASE | SOLVER_OVERSTRICT |
| batch2-struct-004 | batch2 | Structure | MANUAL_REVIEW | ADVERBIAL_CLAUSES | MEDIUM | connector_semantics | LIKELY_GENERATOR_DEFECT | GENERATOR_DESIGN |
| batch2-struct-006 | batch2 | Structure | MANUAL_REVIEW | VERB_FORM_VOICE | MEDIUM | alternate_repair | LIKELY_GENERATOR_DEFECT | GENERATOR_DESIGN |
| batch2-struct-008 | batch2 | Structure | REJECTED | NONFINITE_VERB_PHRASES | MEDIUM | metadata_mismatch | SHOULD_HAVE_BEEN_REVISE | GENERATOR_REALIZATION |
| batch2-struct-012 | batch2 | Structure | REJECTED | INVERSION | HARD | metadata_mismatch | SHOULD_HAVE_BEEN_REVISE | GENERATOR_REALIZATION |
| batch2-we-001 | batch2 | Written Expression | REJECTED | REFERENCE_AND_DETERMINERS | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-002 | batch2 | Written Expression | REJECTED | VERB_FORM_VOICE | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-003 | batch2 | Written Expression | REJECTED | WORD_CLASS_FORM | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-004 | batch2 | Written Expression | REJECTED | REFERENCE_AND_DETERMINERS | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-005 | batch2 | Written Expression | REJECTED | PARALLEL_STRUCTURE | MEDIUM | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-006 | batch2 | Written Expression | REJECTED | VERB_COMPLEMENTATION | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-007 | batch2 | Written Expression | REJECTED | NONFINITE_VERB_PHRASES | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-008 | batch2 | Written Expression | REJECTED | RELATIVE_CLAUSES | MEDIUM | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-009 | batch2 | Written Expression | REJECTED | WORD_CLASS_FORM | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-010 | batch2 | Written Expression | REJECTED | CONNECTORS_CONJUNCTIONS | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-011 | batch2 | Written Expression | REJECTED | REFERENCE_AND_DETERMINERS | HARD | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-012 | batch2 | Written Expression | REJECTED | PARALLEL_STRUCTURE | MEDIUM | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-013 | batch2 | Written Expression | REJECTED | VERB_FORM_VOICE | MEDIUM | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-014 | batch2 | Written Expression | REJECTED | WORD_ORDER_MODIFICATION | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-015 | batch2 | Written Expression | REJECTED | NONFINITE_VERB_PHRASES | MEDIUM | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-016 | batch2 | Written Expression | REJECTED | REFERENCE_AND_DETERMINERS | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-017 | batch2 | Written Expression | REJECTED | COMPARATIVES_DEGREE | MEDIUM | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-018 | batch2 | Written Expression | REJECTED | VERB_COMPLEMENTATION | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-019 | batch2 | Written Expression | REJECTED | PARALLEL_STRUCTURE | MEDIUM | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-020 | batch2 | Written Expression | REJECTED | WORD_CLASS_FORM | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-021 | batch2 | Written Expression | REJECTED | RELATIVE_CLAUSES | HARD | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-022 | batch2 | Written Expression | REJECTED | CONNECTORS_CONJUNCTIONS | MEDIUM | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-023 | batch2 | Written Expression | REJECTED | VERB_FORM_VOICE | HARD | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-024 | batch2 | Written Expression | REJECTED | REFERENCE_AND_DETERMINERS | EASY | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch2-we-025 | batch2 | Written Expression | REJECTED | NONFINITE_VERB_PHRASES | MEDIUM | no_genuine_error | TRUE_GENERATOR_DEFECT | GENERATOR_REALIZATION |
| batch3-struct-009 | batch3 | Structure | REJECTED | COMPARATIVES_DEGREE | HARD | target_mismatch | SHOULD_HAVE_BEEN_REVISE | GENERATOR_DESIGN |
| batch3-struct-011 | batch3 | Structure | REJECTED | WORD_ORDER_MODIFICATION | EASY | target_mismatch | SHOULD_HAVE_BEEN_REVISE | GENERATOR_DESIGN |
| batch3-we-016 | batch3 | Written Expression | REJECTED | WORD_ORDER_MODIFICATION | EASY | metadata_mismatch | SHOULD_HAVE_BEEN_REVISE | GENERATOR_REALIZATION |
| batch3-we-024 | batch3 | Written Expression | DISCARDED | VERB_FORM_VOICE | HARD | revision_failure | LIKELY_GENERATOR_DEFECT | REVISION_FAILURE |

集計:

- REJECTED 30: `no_genuine_error` 25、`metadata_mismatch` 3、`target_mismatch` 2。
- MANUAL_REVIEW 5: Solver AMBIGUOUS 3、A-D disagreement 2。
- DISCARDED 2: Solver NONE 1、revision failure 1。
- 37件の詳細record、question payload、Reviewer checks、independent judgementは `validation_failure_audit.json` に保存した。

## 5. Reviewer REJECT 30件

全30件について、要求されたmetadata、Reviewer verdict/critical failure/primary issue/secondary issues/reason、独立分類をJSONに保存した。下表は監査用の一覧である。

| item_id | batch | section | target | diff | WE error type | scope | Reviewer answer | Reviewer primary issue | independent reason | classification | boundary |
|---|---|---|---|---|---|---|---|---|---|---|---|
| batch2-struct-008 | batch2 | Structure | NONFINITE_VERB_PHRASES | MEDIUM | — | — | B | The marked sentence is grammatical with discovered; the declared answer to discover does not fit, so the item has no valid unique answer. | metadata_mismatch | SHOULD_HAVE_BEEN_REVISE | SHOULD_HAVE_BEEN_REVISE |
| batch2-struct-012 | batch2 | Structure | INVERSION | HARD | — | — | A | The correct completion is has, yielding Never before has such a significant amendment been proposed; it has is ungrammatical here. | metadata_mismatch | SHOULD_HAVE_BEEN_REVISE | SHOULD_HAVE_BEEN_REVISE |
| batch2-we-001 | batch2 | Written Expression | REFERENCE_AND_DETERMINERS | EASY | incorrect_part_of_speech | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-002 | batch2 | Written Expression | VERB_FORM_VOICE | EASY | wrong_verb_form | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-003 | batch2 | Written Expression | WORD_CLASS_FORM | EASY | incorrect_part_of_speech | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-004 | batch2 | Written Expression | REFERENCE_AND_DETERMINERS | EASY | agreement_error | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-005 | batch2 | Written Expression | PARALLEL_STRUCTURE | MEDIUM | incorrect_part_of_speech | clause_level | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-006 | batch2 | Written Expression | VERB_COMPLEMENTATION | EASY | wrong_preposition_collocation | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-007 | batch2 | Written Expression | NONFINITE_VERB_PHRASES | EASY | wrong_verb_form | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-008 | batch2 | Written Expression | RELATIVE_CLAUSES | MEDIUM | incorrect_relative_marker | clause_level | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-009 | batch2 | Written Expression | WORD_CLASS_FORM | EASY | incorrect_part_of_speech | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-010 | batch2 | Written Expression | CONNECTORS_CONJUNCTIONS | EASY | wrong_preposition_collocation | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-011 | batch2 | Written Expression | REFERENCE_AND_DETERMINERS | HARD | agreement_error | cross_clause | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-012 | batch2 | Written Expression | PARALLEL_STRUCTURE | MEDIUM | incorrect_part_of_speech | clause_level | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-013 | batch2 | Written Expression | VERB_FORM_VOICE | MEDIUM | wrong_voice | clause_level | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-014 | batch2 | Written Expression | WORD_ORDER_MODIFICATION | EASY | wrong_word_order | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-015 | batch2 | Written Expression | NONFINITE_VERB_PHRASES | MEDIUM | wrong_verb_form | clause_level | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-016 | batch2 | Written Expression | REFERENCE_AND_DETERMINERS | EASY | missing_required_element | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-017 | batch2 | Written Expression | COMPARATIVES_DEGREE | MEDIUM | wrong_degree_form | clause_level | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-018 | batch2 | Written Expression | VERB_COMPLEMENTATION | EASY | missing_required_element | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-019 | batch2 | Written Expression | PARALLEL_STRUCTURE | MEDIUM | wrong_verb_form | clause_level | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-020 | batch2 | Written Expression | WORD_CLASS_FORM | EASY | incorrect_part_of_speech | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-021 | batch2 | Written Expression | RELATIVE_CLAUSES | HARD | incorrect_relative_marker | cross_clause | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-022 | batch2 | Written Expression | CONNECTORS_CONJUNCTIONS | MEDIUM | incorrect_subordinator | clause_level | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-023 | batch2 | Written Expression | VERB_FORM_VOICE | HARD | wrong_verb_form | cross_clause | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-024 | batch2 | Written Expression | REFERENCE_AND_DETERMINERS | EASY | agreement_error | local | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch2-we-025 | batch2 | Written Expression | NONFINITE_VERB_PHRASES | MEDIUM | incorrect_part_of_speech | sentence_level | NONE | The full sentence contains no genuine grammatical error; the marked part is acceptable standard written English, so the item cannot support a unique error-identification answer. | no_genuine_error | TRUE_GENERATOR_DEFECT | CLEARLY_JUSTIFIED_REJECT |
| batch3-struct-009 | batch3 | Structure | COMPARATIVES_DEGREE | HARD | — | — | B | The item tests finite verb selection/agreement in the that-clause, not comparative degree. | target_mismatch | SHOULD_HAVE_BEEN_REVISE | SHOULD_HAVE_BEEN_REVISE |
| batch3-struct-011 | batch3 | Structure | WORD_ORDER_MODIFICATION | EASY | — | — | D | The item tests selection of a finite lexical verb, not word-order modification. | target_mismatch | SHOULD_HAVE_BEEN_REVISE | SHOULD_HAVE_BEEN_REVISE |
| batch3-we-016 | batch3 | Written Expression | WORD_ORDER_MODIFICATION | EASY | wrong_word_order | local | B | The genuine word-order error is in marked part B, while the generator marks C; the intended answer therefore does not match the independent audit. | metadata_mismatch | SHOULD_HAVE_BEEN_REVISE | SHOULD_HAVE_BEEN_REVISE |

### REJECT root cause

- **25件**: Batch 2 Written Expressionが全件clean sentence。`no_genuine_error`。Reviewerのzero-error blockerは機能しており、REJECTは明確に妥当。
- **2件**: `batch2-struct-008` / `batch2-struct-012`。問題文にはそれぞれB=`discovered`、A=`has`という有効な一意解があるのに、Generator keyがDになっていた。Generator defectだが、key/explanation修正で救済可能なためREVISE相当。
- **2件**: `batch3-struct-009` / `batch3-struct-011`。文法問題としては成立するが、declared targetが実際の現象と不一致。metadata relabelで救済可能なためREVISE相当。
- **1件**: `batch3-we-016`。word-order errorはBだがGeneratorはCを指定。mark/key/explanationの局所修正で救済可能なためREVISE相当。

## 6. REJECT / REVISE境界とReviewer strictness

| 独立分類 | 件数 | rate / 30 | 意味 |
|---|---|---|---|
| clearly justified REJECT | 25 | 83.33 | zero-error clean sentence |
| likely justified REJECT | 0 | 0.0 | 該当なし |
| should-have-been-REVISE | 5 | 16.67 | batch2-struct-008, batch2-struct-012, batch3-struct-009, batch3-struct-011, batch3-we-016 |
| possible over-rejection | 0 | 0.0 | 標準英語としてKeepすべきREJECTは確認されず |
| clear over-rejection | 0 | 0.0 | 該当なし |

したがってv1.1 Reviewerは、**不要なREJECTを無条件に増やしているというより、critical defectの一部でREJECT/REVISE境界が強すぎる**。ただし、zero-error itemを通すほど緩める提案ではない。Human Calibrationでは、key/target mismatchを局所修正とみなすか、clean sentenceを再生成相当とみなすかを確認する。

## 7. Batch 1 / 2 / 3比較

| batch | Struct | WE | surface words Struct mean | surface words WE mean | R1 PASS | R1 REVISE | R1 REJECT | final ACCEPT | manual | discard | reject |
|---|---|---|---|---|---|---|---|---|---|---|---|
| batch1 | 15 | 25 | 12.33 | 10.92 | 38 | 2 | 0 | 37 | 2 | 1 | 0 |
| batch2 | 15 | 25 | 9.6 | 7.76 | 11 | 2 | 27 | 10 | 3 | 0 | 27 |
| batch3 | 15 | 25 | 12.73 | 11.08 | 31 | 6 | 3 | 36 | 0 | 1 | 3 |

### Batch 2異常の最有力原因

最有力は **batch-generation degradation / Generator context driftがBatch 2のWEセグメントに集中したこと**。根拠は以下。

1. Batch 2 WEは25/25件がclean sentenceで、`An ecosystem supports many forms of life.`、`The railway opened ...`、`The course emphasizes ...`のように、marked portionにgenuine errorがない。
2. Batch 2 WEのsurface word countは平均7.76語。Batch 1は10.92語、Batch 3は11.08語。Batch 2 Structureも9.60語で、Batch 1 12.33語、Batch 3 12.73語より短い。
3. Batch 2 WEは前半13/13、後半12/12で失敗。生成順の後半だけの疲労ではなく、WEセクションに切り替わった時点でモードが変わったシグナル。
4. DifficultyはBatch 2 19 EASY / 15 MEDIUM / 6 HARDで、Batch 1 20/15/5、Batch 3 22/14/4と同程度。primary_targetも15カテゴリに分散し、特定targetだけで25件を説明できない。
5. schema passは120/120、version lockも全件同一。したがって、構造schemaやReviewer policyだけではBatch 2の25件を説明できない。

Invocation ID、context-window ID、prompt token履歴はprovenanceにないため、「同一Agent invocationだった」とは断定できない。次回はその識別子と生成順を必ず保存する。

## 8. Reviewer post-PASS anomaly 6件

| item_id | section | Generator | Reviewer | Solver | independent | root cause | validity | unique |
|---|---|---|---|---|---|---|---|---|
| batch2-struct-003 | Structure | A | A | AMBIGUOUS | A | SOLVER_OVERSTRICT | VALID | YES |
| batch2-struct-004 | Structure | D | D | AMBIGUOUS | AMBIGUOUS | GENERATOR_DESIGN | AMBIGUOUS | NO |
| batch2-struct-006 | Structure | B | B | AMBIGUOUS | AMBIGUOUS | GENERATOR_DESIGN | AMBIGUOUS | NO |
| batch1-we-013 | Written Expression | A | A | NONE | NONE | GENERATOR_REALIZATION | AMBIGUOUS | NO |
| batch1-we-007 | Written Expression | C | C | B | B | GENERATOR_REALIZATION | VALID | YES |
| batch1-we-024 | Written Expression | C | C | B | B | GENERATOR_REALIZATION | VALID | YES |

- `batch2-struct-003`: literal insertionではCは第二のvalid optionにならない。Solverがstemの`the university`を落として別文を解いており、primary root causeは`SOLVER_OVERSTRICT`。
- `batch2-struct-004`: Because/Although/Unless/Ifがすべて統語的に成立。semantic relationが不足し、Generator designのunderspecification。Reviewerはsemantic underspecificationを見逃した。
- `batch2-struct-006`: `tested`と`had been tested`の両方が成立。`before publication`だけではpast perfectを強制しない。Generator designとReviewerのtense ambiguity miss。
- `batch1-we-013`: antecedentなしの`It`。Pilot P0-Aの再発で、Generator preventionとReviewer auditは止められず、Solver NONEがcontainmentした。人間にはgrammar/context boundaryとして提示する。
- `batch1-we-007`: 誤りはB=`which mapped`、Generator/ReviewerのCは誤り。Solver Bが独立評価として正しい。
- `batch1-we-024`: 誤りはB=`much`、Generator/ReviewerのCは誤り。Solver Bが独立評価として正しい。

## 9. Reviewer false-negative metrics

Narrowは`Reviewer PASS → Solver AMBIGUOUS/NONE`、BroadはそれにA-D disagreementを加えたもの。

| metric | n | overall denominator | overall rate | solver-reached denominator | solver-reached rate | Structure | WE |
|---|---|---|---|---|---|---|---|
| Narrow Reviewer FN | 4 | 120 | 3.33 | 89 | 4.49 | 3/45 = 6.67%; reached 3/41 = 7.32% | 1/75 = 1.33%; reached 1/48 = 2.08% |
| Broad post-PASS anomaly | 6 | 120 | 5.0 | 89 | 6.74 | 3/45 = 6.67%; reached 3/41 = 7.32% | 3/75 = 4.0%; reached 3/48 = 6.25% |

Narrowは4件、Broadは6件である。Broadの2件はordinary grammar false negativeで、AMBIGUOUS/NONEだけを数える従来metricでは見えなかった。

## 10. P0 hardening effectiveness

ValidationでP0 root cause A=1、B=0、C=0、P0 same-type AUTO_ACCEPT=0を再確認した。Aの1件は`batch1-we-013`で、Generator preventionでは止まらず、Reviewer round1でもPASS、Solver NONE、Orchestrator DISCARDとなった。

これは「P0は失敗した」と一括りにする結果ではない。**AはGenerator/Reviewer防御層を通過し、Solver/Orchestrator層で止まった。B/CはValidationで再発しなかった。** 次に確認すべきは、A型を人間がINVALIDとみなすか、context-dependent edge caseとみなすかである。

## 11. Revision 10件

| item_id | batch | section | revision_count | later verdicts | new defect | final | actual revision |
|---|---|---|---|---|---|---|---|
| batch1-we-003 | batch1 | Written Expression | 1 | PASS | no | ACCEPTED | Revision changed the sentence/stem or construction in the requested dimension and later reviewer PASSed it. |
| batch1-we-023 | batch1 | Written Expression | 1 | PASS | no | ACCEPTED | Revision changed the sentence/stem or construction in the requested dimension and later reviewer PASSed it. |
| batch2-struct-001 | batch2 | Structure | 1 | PASS | no | ACCEPTED | Revision changed the sentence/stem or construction in the requested dimension and later reviewer PASSed it. |
| batch2-struct-009 | batch2 | Structure | 1 | PASS | no | ACCEPTED | Revision changed the sentence/stem or construction in the requested dimension and later reviewer PASSed it. |
| batch3-we-005 | batch3 | Written Expression | 1 | PASS | no | ACCEPTED | Revision changed the sentence/stem or construction in the requested dimension and later reviewer PASSed it. |
| batch3-we-006 | batch3 | Written Expression | 1 | PASS | no | ACCEPTED | Revision changed the sentence/stem or construction in the requested dimension and later reviewer PASSed it. |
| batch3-we-013 | batch3 | Written Expression | 1 | PASS | no | ACCEPTED | Revision changed the sentence/stem or construction in the requested dimension and later reviewer PASSed it. |
| batch3-we-017 | batch3 | Written Expression | 1 | PASS | no | ACCEPTED | Revision changed the sentence/stem or construction in the requested dimension and later reviewer PASSed it. |
| batch3-we-024 | batch3 | Written Expression | 3 | REVISE, REVISE | yes | DISCARDED | Revision 1 changed the item to a local had + past participle error; revision 2 repeated the same text while changing subtype/difficulty metadata, and the item never reached PASS. |
| batch3-we-025 | batch3 | Written Expression | 1 | PASS | no | ACCEPTED | Revision changed the sentence/stem or construction in the requested dimension and later reviewer PASSed it. |

Revision successは **9/10 = 90.0%**。これは単なるlater PASSではなく、9件で修正後のReviewer PASSとSolver一致が確認できた。`batch3-we-024`は、originalのpast perfect意図が`before`で強制されず、revision 1でlocal `had melt`にした後もsubtypeがmodal perfectと不一致、revision 2でdifficulty mismatchが残り、REVISE上限後DISCARDEDとなった。revision loopが必ずしも品質改善を保証しない例としてCalibrationに含める。

## 12. Acceptance rate低下の分解

Pilotは37/40=92.5%、Validationは83/120=69.17%、差は23.33 percentage points。

- round1 REJECT: 30件。最大の損失要因。
- revision failure: 1件。
- Solver AMBIGUOUS: 3件、NONE: 1件、A-D disagreement: 2件。
- LOW confidence 1件は`batch2-struct-004`で、AMBIGUOUSに含まれるため二重計上しない。
- MANUAL_REVIEW 5件、DISCARDED 2件は、上記Solver/revision原因のrouting結果であり、別の追加損失ではない。

Batch 2を除くBatch 1+3は **73/80=91.25%**。Batch 2がこの水準なら約36.5件採用されるところ、実際は10件で、約26.5件のshortfall。Pilot 92.5%との差のうち、Batch 2除外Validationとの差は1.25pp、Batch 2の差は22.08pp相当であり、全体低下のほぼ全てをBatch 2が説明する。

## 13. Generator quality estimate（Human Calibration前の推定）

- Clearly defective initial candidates: **32件**（30 REJECTとして提出された候補 + post-PASSのB/C miskey 2件。うち5件はdefect自体は明確だが、REJECTではなく局所REVISEで救済可能と推定）。
- Likely defective / specification-boundary candidates: **4件**（batch1-we-013、batch2-struct-004、batch2-struct-006、batch3-we-024）。
- Apparently valid but Solver overstrict/boundary: **1件**（batch2-struct-003）。
- Salvageable by revision: **9/10 successful revisions = 90.0%**。
- Reviewer rejected but human基準でそのまま利用可能と見積もる件数: **0/30**。

これらはAI再評価の推定であり、確定値ではない。特にclean sentenceを1 token変更で救えるか、target/key mismatchをREVISEとするかは人間判断で更新する。

## 14. Human Calibration Set

作成物:

- `human_review_calibration_set.json`: pipeline metadata付き46件
- `human_review_calibration_blind.json`: Generator/Reviewer/Solver/failure reasonおよびsource groupを除いたblind payload
- `human_review_calibration_key.json`: pipeline answerとAI independent referenceを分離保存
- `HUMAN_REVIEW_RUBRIC.md`: 8問の判定rubric

構成は **20 AUTO_ACCEPT（Structure 8 / WE 12） + 6 post-PASS anomaly + 15 Reviewer REJECT sample + 5 revision cases = 46件**。Reject sampleは4 Structure reject、10 Batch 2 WE clean output、1 Batch 3 key/span mismatchを含む。Revision caseは成功4件と失敗1件を含む。

## 15. P0 / P1 / P2 recommendations

### P0 — 次validation前に必須

- Human Calibration 46件をblindで実施し、no-error/reference dependency、connector/tense ambiguity、answer-span mismatch、REJECT/REVISE boundaryをadjudicateする。
- Batch generation strategyの診断を追加するまでBatch 2を代表値として扱わない。
- NONE/AMBIGUOUS/disagreementをAUTO_ACCEPTしない現行containmentを維持する。

### P1 — 強く推奨

- Calibration後にGenerator側でBatch/section context drift、WE marked spanへのgenuine error planting、reference/connector/tenseの安全性を検証する。
- Reviewer側でzero-error blockerを維持したまま、answer-key/target metadataのREJECT/REVISE境界を明文化する。
- Structureはconnector relation・tense optionality・literal all-options insertion、WEはreference・marked-span alignment・clean-sentence detectionを重点検証する。
- 次回はinvocation/context ID、generation order、prompt/runtime metadataをprovenanceへ保存する。

### P2 — 将来改善

- Human agreementで再発が確認された場合のみ、Specificationのoperational examplesを追加する。taxonomyの拡張はしない。
- grammar-aware attachment/verb-frame linting、template recurrence tracking、継続calibration panelを検討する。

## 16. Next-hardening recommendation

**F. Prompt変更前にHuman Calibration必須** を推奨する。

現段階でGeneratorのみ、Reviewerのみ、Structureだけ、WEだけのいずれかに直ちに決めるのは早い。Batch 2 degradationはGenerator側を強く示すが、post-PASSにはSolver overstrict 1件、Reviewer/Generatorのordinary false negative 2件、REJECT/REVISE boundary 5件がある。Human Calibrationで層別の原因を確定した後に、次の選択を行う。

変更しないもの: Generator v1.2、Reviewer v1.2、thresholds、acceptance policy、Specification、Taxonomy、Solver、Orchestrator policy、DB、Web site。

## 17. Audit artifacts

- `validation_failure_audit.json`
- `human_review_calibration_set.json`
- `human_review_calibration_blind.json`
- `human_review_calibration_key.json`
- `HUMAN_REVIEW_RUBRIC.md`
