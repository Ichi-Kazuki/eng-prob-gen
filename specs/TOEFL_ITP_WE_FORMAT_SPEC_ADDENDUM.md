# TOEFL ITP Written Expression Format Specification Addendum

**Spec ID:** `TOEFL_ITP_WE_FORMAT_SPEC_ADDENDUM`  
**Spec version:** `1.0.0`  
**Date:** 2026-08-24  
**Machine-readable companion:** `specs/toefl_itp_we_format_spec_addendum.json`  
**Status:** Specification addendum only; no Agent, Solver, Orchestrator, taxonomy, DB, or Website changes are included.

## 1. Purpose and scope

This addendum converts the additional analysis of 125 official TOEFL ITP Written Expression items into a formal, machine-readable format specification for future Generator and Reviewer work.

The existing grammar specification answers:

> **Grammar Specification → what grammatical phenomenon to test**

This addendum answers:

> **WE Format Specification → how a Written Expression item is physically and linguistically constructed**

The addendum is an additional Written Expression item-format layer. It does not replace or rewrite `specs/TOEFL_ITP_GRAMMAR_SPEC.md` or `specs/toefl_itp_grammar_spec.json`.

The current task deliberately does **not** modify:

- Generator v1.1
- Reviewer v1.1
- Solver
- Orchestrator
- grammar taxonomy
- database
- Website

Those changes remain a separate Generator/Reviewer v1.2 design task.

## 2. Evidence and classification contract

Every specification statement that functions as a rule is explicitly classified as one of the following:

| Classification | Meaning |
|---|---|
| **OBSERVED** | A value or distribution directly measured or counted in the official 125-item analysis, or directly measured in the cited AI validation sample when the statement is explicitly identified as validation evidence. It is evidence, not automatically a generation quota. |
| **DERIVED RULE** | A generation or review constraint logically derived from the observed format distributions. It describes the intended ETS-like construction pattern and may be enforced by a future agent. |
| **HEURISTIC** | A practical safety recommendation, tolerance policy, or implementation choice that is not directly measured by the official data. It must not be presented as an official ETS fact. |

The machine-readable companion uses the same labels in every rule object. Observed dimensions are kept separate from derived rules and heuristics so that a future implementation cannot silently promote a recommendation into an official fact.

## 3. Sources of truth and precedence

The addendum is based on the following files:

- `analysis/we_format/WE_FORMAT_ANALYSIS_REPORT.md`
- `analysis/we_format/written_expression_format_official.json`
- `analysis/we_format/written_expression_format_official.csv`
- `analysis/we_format/written_expression_format_validation.json`
- `specs/TOEFL_ITP_GRAMMAR_SPEC.md`
- `specs/toefl_itp_grammar_spec.json`
- `analysis/written_expression_items_all.json`
- `analysis/WRITTEN_EXPRESSION_ANALYSIS_REPORT.md`

When a presentation report and a structured artifact differ, the structured JSON/CSV artifact is authoritative. The official format sample is 125 items: five official Practice Tests, 25 Written Expression items per test. The marked-span sample is 500 spans: four marked spans per item.

The tokenization rule used for the measurements is the source rule: Unicode-aware lexical tokens; letter/number sequences count as words; an internal apostrophe or hyphen remains inside the token; punctuation-only tokens are excluded. The same rule is applied to sentences, marked spans, corrections, and gaps.

## 4. Official format observations

All statements in this section are **OBSERVED** facts from the official 125-item format analysis unless a table explicitly says otherwise.

### 4.1 Sentence length

| Metric | Official value |
|---|---:|
| n | 125 |
| mean | 20.05 words |
| median | 20 words |
| minimum | 10 words |
| maximum | 33 words |
| standard deviation | 4.27 words |

Official sentence-length bins:

| Bin | Count |
|---|---:|
| `<=10` | 1 |
| `11–15` | 15 |
| `16–20` | 49 |
| `21–25` | 48 |
| `26–30` | 10 |
| `31+` | 2 |

In particular, sentences of 15 words or fewer occur in **16/125 items (12.8%)**. This is an official distribution observation, not a required quota for every generated batch.

### 4.2 Marked-span word count

The official sample contains 500 marked spans. Their surface word-count distribution is:

| Metric | Official value |
|---|---:|
| n | 500 |
| mean | 1.29 words |
| median | 1 word |
| minimum | 1 word |
| maximum | 4 words |

| Span word count | Count |
|---|---:|
| 1 word | 375 |
| 2 words | 106 |
| 3 words | 16 |
| 4 words | 3 |
| 5+ words | 0 |

### 4.3 Syntactic span type

Syntactic span type is a separate dimension from surface word count. The official counts are:

| Syntactic span type | Count |
|---|---:|
| `SINGLE_WORD` | 375 |
| `SHORT_PHRASE` | 55 |
| `CLAUSE_OR_CLAUSE_LIKE` | 70 |

The format vocabulary is:

- `SINGLE_WORD`: one lexical token.
- `SHORT_PHRASE`: a 2–4-token non-clausal phrase.
- `LONG_PHRASE`: a 5+ token phrase; no official marked span in this sample was in this category.
- `CLAUSE_OR_CLAUSE_LIKE`: a clause or clause-like unit identified using grammatical role, subtype, or error scope as well as surface length.

**DERIVED RULE:** A word-count rule must not be used as a substitute for syntactic span typing. For example, a multiword clause-like span is not equivalent to an ordinary short phrase merely because both have a small token count.

### 4.4 Marked coverage

Official marked coverage is the ratio of unique marked lexical tokens to sentence word count.

| Metric | Official value |
|---|---:|
| n | 125 |
| mean | 27.1% |
| median | 26.3% |
| minimum | 12.9% |
| maximum | 60.0% |

| Coverage bin | Count |
|---|---:|
| `<20%` | 27 |
| `20–29%` | 54 |
| `30–39%` | 35 |
| `40–49%` | 8 |
| `50–59%` | 0 |
| `>=60%` | 1 |

In particular, `>=60%` coverage occurs in **1/125 items**. This is an official extreme-tail observation. It is not evidence that high coverage should be a normal generation pattern.

### 4.5 Unmarked context

Official unmarked context, measured as unmarked lexical words in the sentence, is:

| Metric | Official value |
|---|---:|
| mean | 14.87 words |
| median | 15 words |
| minimum | 4 words |
| maximum | 27 words |

The official format characteristic is the presence of substantial natural context outside the marked spans. The data do **not** establish a universal minimum context threshold. In particular, four words is the observed sample minimum, not a hard lower bound for all future items.

### 4.6 Span spacing

The official approximate lexical gaps between successive marked spans are:

| Gap | Mean | Median | Range |
|---|---:|---:|---:|
| `A–B` | 3.54 | 4 | 1–6 |
| `B–C` | 3.82 | 4 | 1–7 |
| `C–D` | 3.77 | 4 | 1–7 |

These values are derived from ordered PDF span anchors converted to approximate token-index positions. They are not exact absolute text offsets. The gap values are therefore format evidence and diagnostic reference values, not exact placement constraints.

### 4.7 Correct error span

The marked span containing the official grammatical error has the following distribution:

| Metric | Official value |
|---|---:|
| mean length | 1.27 words |
| median | 1 word |
| minimum | 1 word |
| maximum | 4 words |

| Correct span type | Count |
|---|---:|
| `SINGLE_WORD` | 98 |
| `SHORT_PHRASE` | 12 |
| `CLAUSE_OR_CLAUSE_LIKE` | 15 |

The official data therefore contain multiword and clause-like correct error spans. “The correct span is always one word” is not a valid specification rule.

### 4.8 Correction locality

Official correction locality counts are:

| `correction_locality` | Count |
|---|---:|
| `DEPENDENCY_BASED` | 19 |
| `LOCAL_SHORT_SPAN` | 13 |
| `SEMANTIC_OR_CONTEXT_DEPENDENT` | 11 |
| `LOCAL_SINGLE_TOKEN` | 28 |
| `CLAUSE_LEVEL` | 54 |

This dimension describes the information required to identify and repair the error. A short marked span can still require dependency, clause, semantic, or broader context.

**DERIVED RULE:** Span length and correction locality must not be collapsed into one “local error” dimension.

### 4.9 Decision granularity

Decision granularity is a Written Expression-specific design dimension independent of `primary_target`. Official counts are:

| `decision_granularity` | Count |
|---|---:|
| `FUNCTION_WORD` | 26 |
| `WORD_ORDER` | 6 |
| `CLAUSE_RELATION` | 8 |
| `VERB_FRAME` | 44 |
| `OTHER` | 7 |
| `MORPHOLOGY` | 15 |
| `WORD_CLASS` | 4 |
| `AGREEMENT_DEPENDENCY` | 14 |
| `LOCAL_PHRASE` | 1 |

`primary_target` remains the grammar/content classification inherited from the existing specification. `decision_granularity` records the level at which the test-taker must make the decision in the Written Expression format.

## 5. Official format versus AI validation evidence

The following is **OBSERVED validation evidence**, not an official ETS distribution for the AI set. It compares the official 125-item sample with Validation v1.1 Written Expression, 75 items.

| Metric | Official | AI Validation v1.1 |
|---|---:|---:|
| sentence median | 20 | 10 |
| marked-span median | 1 | 2 |
| marked coverage median | 26.3% | 100% |
| unmarked context median | 15 | 0 |
| `A–B / B–C / C–D` gap medians | 4 / 4 / 4 | 0 / 0 / 0 |
| items with 15 words or fewer | 16/125 | 75/75 |
| items with coverage `>=60%` | 1/125 | 75/75 |
| items whose item mean span length is `<=1.5` words | 110/125 | 3/75 |

These mismatches are the evidence for adding a separate WE format specification. They show that a set may contain grammatically analyzable sentences while still having a format distribution far from the official Written Expression construction.

## 6. Format validity principles

### 6.1 The item model

**DERIVED RULE:** A Written Expression item must be modeled as one complete sentence with four locally inspectable marked spans, usually distributed across the sentence, and with natural unmarked linguistic context between and around those spans.

**DERIVED RULE:** A Written Expression item must not be generated as “the whole sentence divided into four answer options.” A–D identify candidate error locations inside a sentence; they are not intended to cover the complete sentence by default.

**DERIVED RULE:** A design with 100% marked coverage must not be used as the normal generation pattern because it is far outside the official coverage center of gravity.

**HEURISTIC:** A future implementation may use a coverage warning or review flag for unusually high coverage, but no universal hard minimum for unmarked context is authorized by this addendum.

### 6.2 Sentence-first construction order

**DERIVED RULE:** The preferred construction sequence is:

1. Author a natural, complete, academic-style sentence.
2. Validate the sentence’s syntax and meaning before marking spans.
3. Design or inject exactly one genuine grammatical defect.
4. Confirm the error location.
5. Select four locally inspectable spans A–D from the existing sentence.
6. Confirm that the other three spans are grammatically acceptable and that the corrected sentence has no secondary grammatical error.
7. Run span-geometry and format-distribution diagnostics.

**DERIVED RULE:** The implementation must avoid a workflow that first creates four marked parts and then joins them into a sentence. That workflow encourages contiguous marking, zero context, unnatural prose, and coverage inflation.

### 6.3 Span selection

**DERIVED RULE:** Each A–D span must be grammar-relevant, locally identifiable, and a plausible candidate for careful grammatical scrutiny.

**DERIVED RULE:** The four spans should be distributed through the sentence rather than mechanically placed as four adjacent segments.

**DERIVED RULE:** The span selection should avoid unnecessary long spans and should preserve enough unmarked context for syntactic dependency, lexical interpretation, naturalness, and difficulty.

**DERIVED RULE:** Surface word count and syntactic span type must be recorded independently. A word-count cap must not replace syntactic classification.

**DERIVED RULE:** A future format checker must not impose an absolute `max 2 words` or `max 3 words` rule. The official sample contains three 4-word spans, and the correct error span reaches four words.

### 6.4 Coverage policy

**DERIVED RULE:** Coverage must be evaluated as a distribution-aware format property, not as a single arbitrary pass/fail threshold.

The policy has three conceptual bands:

- **Preferred range:** the central empirical region derived from the official item-level coverage distribution.
- **Warning range:** outside the preferred range but still within an observed or plausible tail; requires diagnostic attention rather than automatic rejection.
- **DERIVED RULE — Extreme outlier:** a rare tail pattern such as the official `>=60%` bin, which occurred in 1/125 items, should not be selected deliberately as the normal design.

**HEURISTIC:** The exact preferred and warning numeric boundaries are deferred to Generator v1.2. They should be generated from the official observations using an explicit empirical-quantile method, recorded in machine-readable form, and versioned when chosen. This addendum does not invent a hard threshold.

**DERIVED RULE:** The official `>=60%` observation may be used as an extreme-tail diagnostic flag, but it must not be converted into a universal hard rejection rule without a future design decision and validation evidence.

### 6.5 Context policy

**DERIVED RULE:** The sentence should intentionally retain unmarked context because context supplies syntactic dependency, lexical context, sentence naturalness, and a meaningful difficulty surface.

**HEURISTIC:** Avoid designs in which the marked spans cover almost the entire sentence. This is a safety recommendation derived from the official coverage/context profile, not a claim that every item below an exact context count is invalid.

### 6.6 Difficulty policy

**DERIVED RULE:** Difficulty must not be manufactured by making marked spans longer, making the sentence unnatural, or increasing semantic ambiguity.

**HEURISTIC:** Difficulty should primarily be expressed through grammatical factors such as dependency distance, clause structure, verb frame, subtle morphology, function-word choice, agreement relationships, and plausible-but-incorrect forms. These are design factors, not a claim of a fixed causal conversion from the official format counts to difficulty.

**HEURISTIC:** A future generator should prefer a clear grammatical challenge embedded in natural context over an obscure lexical item or a visibly broken sentence.

## 7. Future Generator v1.2 requirements

The following are **DERIVED RULE** requirements for the next Generator design. They are recorded here only; Generator v1.1 is unchanged by this addendum.

- Construct the complete sentence before choosing A–D spans.
- Maintain exactly four marked spans and one intended erroneous span.
- Preserve natural unmarked context around and between spans.
- Select spans that are locally inspectable but may require broader sentence context to judge.
- Keep span length distribution-aware; do not use an absolute 2-word or 3-word maximum.
- Treat marked coverage as a distribution diagnostic with preferred, warning, and extreme-outlier bands.
- Avoid normalizing all items to 100% marked coverage.
- Keep correction locality and decision granularity as explicit metadata independent of `primary_target`.
- Confirm that the three non-error spans are acceptable and that the corrected sentence has no unintended second error.
- Use geometry diagnostics after span selection, not as a substitute for grammatical validation.

The following are **HEURISTIC** design choices for Generator v1.2:

- Choose exact coverage tolerance bands from a documented empirical-quantile procedure.
- Use batch-level distribution checks as soft targets rather than forcing the official 125-item counts onto small batches.
- Use the official gap medians as reference diagnostics, not as exact token-placement quotas.
- Allow occasional tail items when grammar/content design justifies them, but route extreme format outliers for review.

## 8. Future Reviewer v1.2 requirements

The following **DERIVED RULE** defines the future Reviewer format-check surface. These checks are not implemented in Reviewer v1.1.

The reviewer should evaluate:

- sentence length profile;
- A/B/C/D span length profile;
- marked coverage;
- unmarked context;
- span spacing;
- span type;
- correct span length/type and correction locality;
- decision granularity;
- distance from the official format distribution or an equivalent diagnostic concept.

**DERIVED RULE:** Format validity and grammatical validity must be reported as separate dimensions.

For example, an item may be grammatically valid but far outside the ETS-like format profile. That case is a format/style failure or warning, not automatically a grammar rejection. Conversely, an item may have plausible span geometry but contain two genuine grammatical errors; that is a grammatical validity failure.

**HEURISTIC:** The future reviewer may use separate result namespaces such as `grammar_validity` and `format_validity`, with independent statuses such as `PASS`, `WARN`, `FAIL`, or `NOT_EVALUATED`. The exact status vocabulary is deferred to Reviewer v1.2 implementation design.

## 9. Machine-readable diagnostics

The following diagnostic fields are required in the future WE metadata contract. Their definitions are in the companion JSON.

- `sentence_word_count`
- `span_word_counts.A`
- `span_word_counts.B`
- `span_word_counts.C`
- `span_word_counts.D`
- `mean_span_length`
- `max_span_length`
- `marked_coverage_ratio`
- `unmarked_word_count`
- `gap_A_B`
- `gap_B_C`
- `gap_C_D`
- `correct_span_word_count`
- `correct_span_type`
- `correction_locality`
- `decision_granularity`
- `format_distribution_distance` (or a documented equivalent)

The exact definition of the fields is deliberately centralized in `specs/toefl_itp_we_format_spec_addendum.json` so future Agent work can consume one machine-readable contract.

## 10. Confidence and limitations

**OBSERVED / HIGH confidence:** The official sentence counts, span word counts, coverage counts, unmarked context counts, correct-span counts, correction-locality counts, and decision-granularity counts are based on the full official 125-item analysis and its 500 marked spans.

**OBSERVED / HIGH confidence:** The official sentence word count was reconciled using the source token rule, with zero remeasurement deltas in the structured official analysis.

**OBSERVED / APPROXIMATE geometry:** Span placement and gap values come from ordered PDF geometry. The official PDF text layer does not provide reliable exact token offsets, so the positions are approximate token-index estimates.

**DERIVED RULE:** PDF-derived gap values must not be converted into over-precise absolute placement constraints.

**HEURISTIC:** Use gap medians and ranges as reference evidence for diagnostics and batch-level shape, while allowing grammatical and natural-language requirements to take precedence over exact geometry.

## 11. Change boundary and next step

This addendum is complete as a specification artifact only. It does not alter any Agent or runtime behavior.

The next implementation task, if authorized separately, is a Generator/Reviewer v1.2 design that consumes this addendum and adds format metadata and checks without changing the shared grammar taxonomy.
