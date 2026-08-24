# TOEFL ITP Grammar Item Specification

**Spec version:** 1.0.0
**Taxonomy version:** 1.1
**Date:** 2026-08-23
**Machine-readable companion:** `specs/toefl_itp_grammar_spec.json`

> **How to read this document.** Every claim below is labeled as one of three kinds:
>
> - **OBSERVED** — a fact directly measured/counted from the 200 analyzed ETS items.
> - **DERIVED RULE** — a generation rule derived from an OBSERVED fact, intended to be followed fairly strictly.
> - **HEURISTIC** — a practical recommendation the data alone cannot fully determine (e.g. a tolerance range, a batch-level target split). Heuristics may be adjusted with experience; they are not hard constraints.
>
> Do not treat OBSERVED percentages as fixed generation quotas. Do not treat HEURISTIC ranges as OBSERVED facts.

---

## 1. Purpose and Scope

This specification exists so that a future AI item-generation pipeline (Generator / Reviewer / Solver agents — **not built yet**, see §16 of the originating task) has a single, versioned reference for what a well-formed, ETS-style TOEFL ITP Level 1 grammar practice item looks like, structurally.

**In scope:**

- New-item generation for **TOEFL ITP Level 1**:
  - **Structure, Part A** (incomplete-sentence completion, Q1–15 in each official section).
  - **Written Expression, Part B** (error-identification, Q16–40 in each official section).

**Analysis source:**

- 5 official ETS TOEFL ITP Practice Tests: **B, C, D, E, F**. (Practice Test A was not present in the source materials and was not analyzed — it is a gap in the source library, not an intentional exclusion.)
- **Structure: 75 items** (15 × 5 tests).
- **Written Expression: 125 items** (25 × 5 tests).
- **Total: 200 items.**

**Explicitly out of scope for this document:**

- This specification does **not** reproduce, quote, or closely paraphrase any ETS item. It describes **abstract design features** (grammar-topic distribution, sentence-length statistics, distractor-construction mechanisms, etc.) distilled from the 200-item sample, for the purpose of generating **independently authored, new** items that resemble the official test's design patterns — not its content.
- This specification is document-only. It does **not** implement a Generator Agent, Reviewer Agent, Solver Agent, new TOEFL items, or a problem database. Those are future work.

---

## 2. Source Data and Confidence

| Section | n | Practice Tests | Primary dataset files |
|---|---:|---|---|
| Structure (Part A) | 75 | B, C, D, E, F | `analysis/structure_items_all.json`, `.csv` |
| Written Expression (Part B) | 125 | B, C, D, E, F | `analysis/written_expression_items_all.json`, `.csv` |
| **Total** | **200** | B, C, D, E, F | — |

**Value precedence:** Where a Markdown analysis report and the underlying JSON/CSV disagree, the **JSON/CSV is authoritative**. Every number in this specification was recomputed directly from `structure_items_all.json` and `written_expression_items_all.json` as part of writing this document, and cross-checked against `STRUCTURE_ANALYSIS_REPORT.md` / `WRITTEN_EXPRESSION_ANALYSIS_REPORT.md`; no discrepancies were found between the two sources at the time of writing.

**Confidence labeling.** Throughout this document, OBSERVED facts carry a confidence tag:

- **HIGH** — measured from the full 75- or 125-item sample, or a total ≥ ~15 across both sections; stable enough to anchor generation rules.
- **MEDIUM** — measured from the full sample but with a smaller sub-count (roughly 6–14 total occurrences), or a distribution with a long unevenly-populated tail; usable as a guide but expect more batch-to-batch variance.
- **LOW** — based on very few occurrences (typically ≤ 5, including single-instance or zero-instance categories); treat as suggestive, not authoritative. A LOW-confidence, low-frequency category is **not** evidence that the category should be avoided in generation — see §6 and §13.

---

## 3. Shared Grammar Taxonomy

Structure and Written Expression **share one taxonomy** (`analysis/grammar_taxonomy.json` v1.1, `analysis/GRAMMAR_TAXONOMY.md`). It has three tiers:

- **`primary_target`** — a closed set of 15 stable syntactic categories (the practical ceiling; do not casually add a 16th — see the taxonomy changelog's decision criteria for what would justify it).
- **`subtype`** — a free-form string naming the exact construction tested (grows without limit).
- **`secondary_features`** — free-form tags for co-occurring, non-primary grammar phenomena.

It also defines a shared, closed, 15-value **`tested_error_type`** vocabulary (Structure's `distractors.*.error_type`; Written Expression's `error_span.tested_error_type`) describing *how* an error/distractor is structurally wrong, independent of *what topic* (`primary_target`) it tests.

### 3.1 primary_target — all 15 categories

**Confidence:** HIGH (complete census across all 200 items; every item has exactly one `primary_target`).

| id | Definition (abridged) | Structure (n=75) | Written Expr. (n=125) | Total (n=200) | Confidence |
|---|---|---:|---:|---:|---|
| `CLAUSE_STRUCTURE` | Independent-clause well-formedness; fragment/run-on detection; basic subject–verb agreement. | 12 (16.0%) | 7 (5.6%) | 19 (9.5%) | HIGH |
| `NOUN_CLAUSES` | that-clauses / embedded questions as subject, object, or complement; word order inside the clause. | 6 (8.0%) | 0 (0.0%) | 6 (3.0%) | MEDIUM |
| `RELATIVE_CLAUSES` | Restrictive/non-restrictive relative clauses; relative-pronoun choice/case; clause-internal parallelism. | 9 (12.0%) | 7 (5.6%) | 16 (8.0%) | HIGH |
| `ADVERBIAL_CLAUSES` | Internal structure of time/cause/concession/condition/purpose subordinate clauses (clause vs. phrase vs. inverted form). | 3 (4.0%) | 0 (0.0%) | 3 (1.5%) | LOW |
| `CONNECTORS_CONJUNCTIONS` | Choosing the correct connector word/phrase (cause, contrast, comparison, etc.) among conjunction/preposition/adverb options. | 5 (6.7%) | 7 (5.6%) | 12 (6.0%) | MEDIUM |
| `VERB_FORM_VOICE` | Tense/aspect/active-passive selection for the finite main verb. | 1 (1.3%) | 10 (8.0%) | 11 (5.5%) | MEDIUM |
| `VERB_COMPLEMENTATION` | What correctly follows a linking verb (predicate nominative/adjective) or causative/perception verb (object complement); also verb/participle/adjective-governed preposition collocations. | 7 (9.3%) | 16 (12.8%) | 23 (11.5%) | HIGH |
| `NONFINITE_VERB_PHRASES` | Participle/infinitive/gerund form selection (reduced relative clauses, result participles, purpose infinitives, etc.). | 9 (12.0%) | 13 (10.4%) | 22 (11.0%) | HIGH |
| `COMPARATIVES_DEGREE` | Comparative/superlative structures; degree constructions (enough/so/too/as...as). | 5 (6.7%) | 3 (2.4%) | 8 (4.0%) | MEDIUM |
| `PARALLEL_STRUCTURE` | Syntactic parallelism across coordinated/correlative elements or list items. | 1 (1.3%) | 15 (12.0%) | 16 (8.0%) | HIGH |
| `WORD_ORDER_MODIFICATION` | Internal word order of noun-modifying elements (adjective phrases, appositives, participial modifiers, NP structure). | 8 (10.7%) | 5 (4.0%) | 13 (6.5%) | MEDIUM |
| `INVERSION` | Subject–auxiliary inversion after fronted negative/place adverbials or elliptical conditionals. | 4 (5.3%) | 0 (0.0%) | 4 (2.0%) | LOW |
| `EXISTENTIAL_EXPLETIVE` | Expletive "there + be" / "it + be" constructions. | 3 (4.0%) | 0 (0.0%) | 3 (1.5%) | LOW |
| `REFERENCE_AND_DETERMINERS` | Pronoun–antecedent agreement; articles; quantifiers; countable/uncountable choice. | 2 (2.7%) | 28 (22.4%) | 30 (15.0%) | HIGH |
| `WORD_CLASS_FORM` | Derivational/part-of-speech form (adjective/adverb/noun/verb) required by a given syntactic slot. Added in taxonomy v1.1. | 0 (0.0%) | 14 (11.2%) | 14 (7.0%) | MEDIUM |
| **Total** | | **75** | **125** | **200** | |

**Representative subtypes** (illustrative, not exhaustive — the full 194-subtype list across both sections lives in the raw JSON/CSV):

- `CLAUSE_STRUCTURE`: main clause (subject + finite verb) identification; sentence fragment vs. independent clause; subject–verb agreement across an intervening phrase.
- `NOUN_CLAUSES`: embedded-question word order; that-clause as subject; that-clause as object complement.
- `RELATIVE_CLAUSES`: non-restrictive relative clause with parallel coordinate predicate; relative-pronoun case (who/whom/whose) selection.
- `ADVERBIAL_CLAUSES`: time clause introduced by "when"; concessive clause structure; conditional clause structure.
- `CONNECTORS_CONJUNCTIONS`: preposition vs. subordinating conjunction (cause); contrast connector selection (although vs. despite vs. however).
- `VERB_FORM_VOICE`: past perfect vs. simple past selection; active vs. passive voice in the main clause.
- `VERB_COMPLEMENTATION`: predicate nominative after a linking verb; object complement after a causative verb; verb/participle/adjective-governed preposition collocation ("benefit from," "known for," "rich in").
- `NONFINITE_VERB_PHRASES`: reduced passive relative clause; participial phrase of result; infinitive modifying an ordinal/superlative noun; gerund vs. infinitive complement.
- `COMPARATIVES_DEGREE`: adjective + enough + to-infinitive result construction; so + adjective + that-clause; as...as comparative.
- `PARALLEL_STRUCTURE`: parallel verb forms in a list; correlative-conjunction parallelism (not only...but also).
- `WORD_ORDER_MODIFICATION`: appositive noun-phrase placement; noun + postpositive adjective phrase.
- `INVERSION`: inversion after "Not until..."; inversion after a fronted place adverbial; conditional inversion (Had.../Were.../Should...).
- `EXISTENTIAL_EXPLETIVE`: expletive "there + be" vs. pronoun/determiner; expletive "it + be."
- `REFERENCE_AND_DETERMINERS`: pronoun with no clear antecedent; quantifier–noun countability agreement; article selection.
- `WORD_CLASS_FORM`: adjective required, adverb used (or vice versa); noun required, adjective used as clause subject; cardinal used where an ordinal is required.

**IMPORTANT:** A 0.0% total in the table above (`WORD_CLASS_FORM` in Structure; `NOUN_CLAUSES`/`ADVERBIAL_CLAUSES`/`INVERSION`/`EXISTENTIAL_EXPLETIVE` in Written Expression) reflects that this 200-item sample happened not to surface that pattern in that section's item format — **it must not be read as "this category is forbidden in that section."** See §7.2 and §8.2.

### 3.2 tested_error_type — all 15 values

**Confidence:** HIGH for Structure (complete census of 225 distractor slots); HIGH for Written Expression (complete census of 125 items).

These two counts are **not directly comparable** — Structure's count is over 225 *distractor slots* (3 wrong answers × 75 items, i.e. "how often was this error mechanism used to construct a wrong answer"), while Written Expression's count is over 125 *items* (1 actual error per item, i.e. "how often did the single planted error use this mechanism"). Each section's distribution is analyzed independently in §7.5/§7.6 and §8.3.

| id | Description | Structure distractors (n=225) | Written Expr. items (n=125) |
|---|---|---:|---:|
| `missing_required_element` | A required element (subject, verb, connector, etc.) is missing. | 42 (18.7%) | 6 (4.8%) |
| `extraneous_element` | An unnecessary/duplicated element is added. | 34 (15.1%) | 6 (4.8%) |
| `wrong_word_order` | Elements present but incorrectly ordered. | 34 (15.1%) | 5 (4.0%) |
| `fragment` | Not a complete clause (missing finite verb or subject). | 34 (15.1%) | 0 (0.0%)¹ |
| `wrong_complementation` | Wrong complement structure for a linking/causative/perception verb (not preposition collocation). | 17 (7.6%) | 0 (0.0%)² |
| `incorrect_subordinator` | Wrong subordinating conjunction for the intended relation. | 16 (7.1%) | 3 (2.4%) |
| `incorrect_part_of_speech` | Wrong part of speech (not comparative/superlative — see `wrong_degree_form`). | 10 (4.4%) | 35 (28.0%) |
| `incorrect_relative_marker` | Wrong relative pronoun/marker or case. | 9 (4.0%) | 6 (4.8%) |
| `wrong_verb_form` | Wrong tense/aspect/form of a verb. | 9 (4.0%) | 21 (16.8%) |
| `double_subject` | Subject redundantly duplicated (e.g. relative pronoun + resumptive pronoun). | 9 (4.0%) | 1 (0.8%) |
| `wrong_voice` | Active/passive voice error. | 6 (2.7%) | 4 (3.2%) |
| `incorrect_reference` | Pronoun has no clear/appropriate antecedent. | 2 (0.9%) | 3 (2.4%) |
| `agreement_error` | Subject–verb or noun–quantifier number-agreement error. | 2 (0.9%) | 21 (16.8%) |
| `wrong_degree_form` | Comparative/superlative/positive confusion, or wrong degree/intensity marker (e.g. "very" for "so"). Added v1.1. | 1 (0.4%) | 2 (1.6%) |
| `wrong_preposition_collocation` | Fixed lexical preposition/collocation error (governed or standalone). Added v1.1. | 0 (0.0%)³ | 12 (9.6%) |
| **Total** | | **225** | **125** |

¹ `fragment` cannot occur in Written Expression by format definition — every WE sentence is presented complete; a bare fragment is not a plausible "one wrong word/phrase" error. This is a structural impossibility for that section, not a sampling gap.
² All previously force-fit `wrong_complementation` Written Expression items were reclassified to the more precise `wrong_preposition_collocation` in the v1.0→v1.1 taxonomy update (see `GRAMMAR_TAXONOMY_CHANGELOG.md`).
³ Not observed as a Structure distractor mechanism in this 75-item sample; Written Expression's format (spotting an error in an already-complete sentence) appears to surface lexical-collocation errors far more readily than Structure's format (choosing among four candidate completions) does. Not forbidden for Structure, just unobserved here.

---

## 4. Difficulty Framework

**Status: HEURISTIC**, shared by both sections.

Three generation-facing tiers are defined: **EASY / MEDIUM / HARD**.

These tiers are **not** a fixed linear mapping from the OBSERVED `estimated_difficulty_ai` 1–5 field. That field is an **AI-generated structural estimate produced during analysis, not an ETS official difficulty rating**, and it must never be presented downstream as one (see §7.8, §8.10).

Factors that should drive difficulty (in order of how directly they were observed to correlate with the AI's own structural difficulty estimate during analysis):

- syntax complexity (nesting depth, number of clauses)
- structural dependency distance (how far apart two grammatically related elements sit)
- distractor similarity (Structure) / distractor plausibility (Written Expression)
- error scope (Written Expression only: `local` < `clause_level` < `sentence_level`/`cross_clause`, directionally — see §8.7 caveat)
- rarity/unfamiliarity of the tested construction

**Explicit non-factor:** vocabulary specialization or rarity must **not**, by itself, be used to raise difficulty. A HARD item should be hard because of its grammar, not because it uses an obscure word.

**Approximate reference only** (not a formula): both sections' observed `estimated_difficulty_ai` distributions cluster in the low-to-mid range (Structure: values 2–4 only, mean 2.96; Written Expression: values 1–4 only, mean 2.30). Neither section produced a "5" in this 200-item sample. A generated HARD item should generally still resemble this observed ceiling rather than inventing more extreme difficulty than ETS itself produced here.

---

## 5. Structure Part A Specification

### 5.1 Item format

**OBSERVED:**

- An incomplete sentence with exactly one blank.
- Exactly four answer choices (A–D).
- Exactly one choice restores a grammatically complete, standard-written-English sentence.
- The other three choices ("distractors") represent plausible grammatical confusions, not random nonsense.

**DERIVED RULE:**

- Generated items must have exactly 4 options and exactly 1 correct option.
- The correct option must yield a complete, well-formed sentence with no residual errors.
- Distractors must be built from the OBSERVED `tested_error_type` mechanisms (§3.2, §5.5), not invented ad hoc.

### 5.2 Primary target distribution

See §3.1 for the full OBSERVED/total table. Structure-only counts, restated with **generation guidance ranges**:

| primary_target | Observed % (n=75) | Generation guidance range (HEURISTIC) |
|---|---:|---:|
| `CLAUSE_STRUCTURE` | 16.0% | 10–22% |
| `RELATIVE_CLAUSES` | 12.0% | 8–17% |
| `NONFINITE_VERB_PHRASES` | 12.0% | 8–17% |
| `WORD_ORDER_MODIFICATION` | 10.7% | 7–15% |
| `VERB_COMPLEMENTATION` | 9.3% | 6–13% |
| `NOUN_CLAUSES` | 8.0% | 5–11% |
| `COMPARATIVES_DEGREE` | 6.7% | 4–9% |
| `CONNECTORS_CONJUNCTIONS` | 6.7% | 4–9% |
| `INVERSION` | 5.3% | 3–7% |
| `ADVERBIAL_CLAUSES` | 4.0% | 3–6% |
| `EXISTENTIAL_EXPLETIVE` | 4.0% | 3–6% |
| `REFERENCE_AND_DETERMINERS` | 2.7% | 2–4% |
| `VERB_FORM_VOICE` | 1.3% | 1–3% |
| `PARALLEL_STRUCTURE` | 1.3% | 1–3% |
| `WORD_CLASS_FORM` | 0.0% | 0–4% |

**HEURISTIC derivation method (disclosed for transparency):** guidance range ≈ [0.65×observed%, 1.4×observed%], with a minimum band width of 2 percentage points, and a floor of 0–4% for categories observed at 0%. This band is deliberately wider than a naive confidence interval to tolerate the natural sampling variance of small generated batches; it is **not** a statistically derived confidence interval, and it is **not** a quota — see the IMPORTANT note in §3.1 and §12.

### 5.3 Sentence length

**OBSERVED** (`sentence_word_count`, confidence HIGH):

| Statistic | Value |
|---|---:|
| Mean | 19.97 |
| Median | 20 |
| Min | 10 |
| Max | 27 |
| Stdev | 4.34 |

Distribution (5-word bins): 10–14: 11 · 15–19: 22 · 20–24: 27 · 25–27: 15.

**DERIVED RULE:** Generated Structure items should normally fall within the observed 10–27 word range, concentrated around 15–24 words.

**HEURISTIC:** Target a batch mean near 20 words. Include occasional short items (~10–14 words) and occasional long items (~25–27 words) — do not make every item the same length.

### 5.4 Clause count

**OBSERVED** (`clause_count`, finite clauses only; infinitives/gerunds/participles not counted; confidence HIGH):

| clause_count | count | % |
|---:|---:|---:|
| 1 | 27 | 36.0% |
| 2 | 37 | 49.3% |
| 3 | 10 | 13.3% |
| 4 | 1 | 1.3% |

Mean 1.80, median 2.

**DERIVED RULE:** A generated batch's clause-count shape should not deviate sharply from: roughly a third single-clause, roughly half two-clause, a minority (10–15%) three-or-more-clause.

**HEURISTIC:** For a 15-item batch: ≈5 items at 1 clause, ≈7–8 at 2 clauses, ≈2–3 at 3+ clauses.

### 5.5 Distractor design

**OBSERVED** `error_type` distribution over all 225 distractor slots — see §3.2 table (Structure column).

The top 4 mechanisms (`missing_required_element`, `extraneous_element`, `wrong_word_order`, `fragment`) together account for **64.0%** of all distractors — these are the basic "types" of TOEFL ITP Structure wrong answers.

**DERIVED RULE:** Each distractor must be constructed using one of the 15 shared `tested_error_type` mechanisms (§3.2), favoring — but not restricted to — the four dominant mechanisms above.

**Hard requirements per distractor** (DERIVED RULE, restated from the task brief):

1. Superficially plausible — a learner must be able to imagine picking it.
2. The grammatical difference from the correct answer must be explicitly describable in one sentence.
3. Not obviously nonsensical.
4. Must not create a second defensible correct answer.
5. Must not be eliminable through vocabulary knowledge alone — the flaw must be grammatical/structural, not lexical rarity.

### 5.6 Correct answer position

**OBSERVED** (confidence HIGH):

| Position | count | % |
|---|---:|---:|
| A | 18 | 24.0% |
| B | 21 | 28.0% |
| C | 20 | 26.7% |
| D | 16 | 21.3% |

**DERIVED RULE:** Over a large generated corpus, correct-answer position should trend toward roughly even across A–D.

**HEURISTIC:** Do **not** force exactly 25% per option in every small batch — the observed 21.3%–28.0% range across a real 75-item ETS sample shows natural variance is normal and acceptable; only the long-run trend needs to stay balanced.

### 5.7 Vocabulary domain

**OBSERVED** (confidence MEDIUM): 73 unique `vocabulary_domain` values across 75 items; only `botany` and `zoology/marine biology` repeat (2 each), all others appear once.

**DERIVED RULE:** Generated items should draw from a wide range of academic/general-interest domains — natural science, social science, history, art, humanities, geography, biography, technology, and similar — reproducing this observed *diversity*, not any specific observed domain list.

**HEURISTIC:** No fixed domain roster is mandated. Background/world knowledge must **never** be required to select the correct answer — every fact needed must be inferable from the sentence's own grammar, not from outside knowledge of the topic.

### 5.8 Difficulty characteristics

**OBSERVED** (confidence MEDIUM):

| Metric (1–5 scale) | Mean | Distribution |
|---|---:|---|
| `syntactic_complexity` | 2.77 | 2=30, 3=32, 4=13 (1, 5 not observed) |
| `distractor_similarity` | 3.27 | 2=2, 3=52, 4=20, 5=1 (1 not observed) |
| `estimated_difficulty_ai` | 2.96 | 2=18, 3=42, 4=15 (1, 5 not observed) |

> **`estimated_difficulty_ai` is not an ETS official difficulty rating.** It is a structural estimate produced by the analysis pipeline from sentence length, clause nesting, and distractor confusability. It does not correspond to actual test-taker pass rates and must not be represented as ETS's own difficulty grading.

**DERIVED RULE:** Difficulty control in generation should use the factors in §4 (syntax complexity, clause nesting, distractor similarity, construction rarity, dependency distance) — **not** harder vocabulary.

---

## 6. Written Expression Part B Specification

### 6.1 Item format

**OBSERVED:**

- A complete sentence with exactly four marked/underlined portions (A–D).
- Exactly one portion contains a grammatical error.
- The other three portions are standard, acceptable written English.
- The learner selects the erroneous portion.

**DERIVED RULE:**

- Generated items must have exactly 4 marked portions and exactly 1 erroneous portion.
- The 3 non-erroneous portions must be genuinely correct standard written English — not merely "less wrong" than the error.
- Exactly one genuine grammatical error may exist anywhere in the sentence, marked or unmarked (no incidental second error).

### 6.2 Primary target distribution

Written-Expression-only counts, restated with generation guidance ranges (same HEURISTIC method as §5.2):

| primary_target | Observed % (n=125) | Generation guidance range (HEURISTIC) |
|---|---:|---:|
| `REFERENCE_AND_DETERMINERS` | 22.4% | 15–31% |
| `VERB_COMPLEMENTATION` | 12.8% | 8–18% |
| `PARALLEL_STRUCTURE` | 12.0% | 8–17% |
| `WORD_CLASS_FORM` | 11.2% | 7–16% |
| `NONFINITE_VERB_PHRASES` | 10.4% | 7–15% |
| `VERB_FORM_VOICE` | 8.0% | 5–11% |
| `CONNECTORS_CONJUNCTIONS` | 5.6% | 4–8% |
| `RELATIVE_CLAUSES` | 5.6% | 4–8% |
| `CLAUSE_STRUCTURE` | 5.6% | 4–8% |
| `WORD_ORDER_MODIFICATION` | 4.0% | 3–6% |
| `COMPARATIVES_DEGREE` | 2.4% | 2–4% |
| `NOUN_CLAUSES` | 0.0% | 0–4% |
| `ADVERBIAL_CLAUSES` | 0.0% | 0–4% |
| `INVERSION` | 0.0% | 0–4% |
| `EXISTENTIAL_EXPLETIVE` | 0.0% | 0–4% |

**IMPORTANT:** The four 0.0%-observed categories reflect this sample's item format tendencies (whole-clause / connector-selection phenomena are Structure's natural territory; Written Expression's "find the local word-level error" format favors word-class/reference/agreement/complementation errors instead) — they are not prohibited categories.

### 6.3 Tested error type distribution

See §3.2 for the full 15-value table (Written Expression column). Restated with definitions and abstract patterns:

| tested_error_type | Observed count/% (n=125) | Definition | Representative abstract pattern |
|---|---:|---|---|
| `incorrect_part_of_speech` | 35 (28.0%) | Wrong part of speech (not degree confusion). | A word occupies a modifier/head-noun/subject/complement slot requiring one derivational form (adjective/adverb/noun/verb), but a different form is used. |
| `wrong_verb_form` | 21 (16.8%) | Wrong tense/aspect/form of a verb. | Verb tense/aspect doesn't match the sentence's established time-frame or surrounding auxiliary. |
| `agreement_error` | 21 (16.8%) | Subject–verb or noun–quantifier number mismatch. | Singular subject with plural verb (or vice versa); quantifier mismatched to countable/uncountable noun. |
| `wrong_preposition_collocation` | 12 (9.6%) | Fixed lexical preposition/collocation violated. Added v1.1. | A verb/adjective/participle/noun's fixed governed preposition (or a standalone paired-preposition idiom) is swapped for a plausible-but-wrong one. |
| `incorrect_relative_marker` | 6 (4.8%) | Wrong relative pronoun/case. | who/whom/which/that/whose chosen incorrectly for the antecedent or clause role. |
| `extraneous_element` | 6 (4.8%) | Unnecessary/duplicated element added. | An extra word or duplicated phrase is wedged into an otherwise complete structure. |
| `missing_required_element` | 6 (4.8%) | Required element omitted. | A phrase/clause is missing an element needed for well-formedness. |
| `wrong_word_order` | 5 (4.0%) | Elements present but misordered. | Correct words, wrong sequence. |
| `wrong_voice` | 4 (3.2%) | Active/passive mismatch. | The logical subject/object relationship requires the opposite voice. |
| `incorrect_reference` | 3 (2.4%) | Pronoun lacks a clear/appropriate antecedent. | A pronoun's referent is missing, ambiguous, or mismatched. |
| `incorrect_subordinator` | 3 (2.4%) | Wrong subordinating conjunction. | The chosen subordinator doesn't match the intended semantic/syntactic relation. |
| `wrong_degree_form` | 2 (1.6%) | Comparative/superlative/positive confusion, or wrong degree/intensity marker. Added v1.1. | Superlative used where comparative is required, or "very" used where "so...that" is required. |
| `double_subject` | 1 (0.8%) | Subject redundantly duplicated. | A relative pronoun co-occurs with a resumptive pronoun repeating the same referent. |
| `fragment` | 0 (0.0%) | N/A for this section (see §3.2 footnote 1) — cannot occur by format definition. | — |
| `wrong_complementation` | 0 (0.0%) | N/A — fully superseded by `wrong_preposition_collocation` for this section (see §3.2 footnote 2). | — |

> No ETS source sentence text is reproduced here; the "representative abstract pattern" column is a generalized description, not a transcription of any specific item.

### 6.4 Error span type

**OBSERVED** `error_span.span_type` (confidence MEDIUM):

| span_type | count | % |
|---|---:|---:|
| noun_phrase | 24 | 19.2% |
| verb_phrase | 22 | 17.6% |
| adjective | 16 | 12.8% |
| prepositional_phrase | 15 | 12.0% |
| pronoun | 9 | 7.2% |
| relative_marker | 7 | 5.6% |
| gerund_phrase | 6 | 4.8% |
| adverb | 5 | 4.0% |
| determiner | 5 | 4.0% |
| conjunction | 4 | 3.2% |
| participial_phrase | 4 | 3.2% |
| infinitive_phrase | 3 | 2.4% |
| comparative_marker | 3 | 2.4% |
| quantifier | 2 | 1.6% |

**DERIVED RULE:** Generated batches should not concentrate error spans in one or two `span_type`s. The observed top four (61.6% combined) are a reasonable center of gravity, but the ten-value long tail should also appear across a sufficiently large batch.

### 6.5 Underlined-part design

Not just the correct (erroneous) span but all three non-erroneous spans must look like plausible test targets.

**OBSERVED grammatical_role of the actual error span** (n=125, confidence MEDIUM): `noun_phrase` 24 (19.2%) · `verb_phrase` 22 (17.6%) · `preposition` 12 (9.6%) · `adjective` 12 (9.6%) · `main_verb` 10 (8.0%) · `pronoun` 9 (7.2%) · `relative_pronoun` 7 (5.6%) · `adverb` 7 (5.6%) · `conjunction` 4 (3.2%) · `subject` 4 (3.2%) · `predicate_adjective` 4 (3.2%) · `determiner` 3 (2.4%) · `quantifier` 2 (1.6%) · `noun_modifier` 2 (1.6%) · `article` 2 (1.6%) · `gerund` 1 (0.8%).

**OBSERVED grammatical_role of the three dummy (non-error) spans** (n=375, confidence MEDIUM): `noun_phrase` 93 (24.8%) · `main_verb` 59 (15.7%) · `verb_phrase` 47 (12.5%) · `adjective` 41 (10.9%) · `preposition` 25 (6.7%) · `subject` 16 (4.3%) · `adverb` 16 (4.3%) · `noun_modifier` 15 (4.0%) · `conjunction` 13 (3.5%) · `quantifier` 11 (2.9%) · `relative_pronoun` 9 (2.4%) · `predicate_adjective` 7 (1.9%) · `gerund` 6 (1.6%) · `auxiliary` 5 (1.3%) · `infinitive_marker` 4 (1.1%) · `determiner` 2 (0.5%) · `object` 2 (0.5%) · `prepositional_phrase` 2 (0.5%) · `pronoun` 1 (0.3%) · `article` 1 (0.3%).

Notably, `main_verb` is a dummy span roughly **2×** as often (15.7%) as it is the actual error (8.0%) — correct main verbs are a frequently-used, plausible-looking non-error.

**DERIVED RULE (underlined-part design):**

1. All 4 marked portions must be natural candidates for grammatical scrutiny — a test-taker should be able to imagine each one being the error before reading closely.
2. The correct (erroneous) span must not be conspicuously longer or shorter than the 3 dummy spans.
3. The correct (erroneous) span must not be obviously strange in isolation — detecting it must require reading it in context.
4. The 3 dummy spans should sit where a careful reader would plausibly want to double-check them, not on trivial filler words.

### 6.6 Error location

**OBSERVED** `error_location` (n=125, confidence MEDIUM): `sentence_initial` 13 (10.4%) · `early` 22 (17.6%) · `middle` 28 (22.4%) · `late` 31 (24.8%) · `sentence_final` 31 (24.8%).

**DERIVED RULE:** Randomize error location per item, but keep the batch-level shape similar to observed (slight skew toward `late`/`sentence_final`, `sentence_initial` least common) rather than clustering all errors in one position.

### 6.7 Error scope

**OBSERVED** `error_scope` (n=125, confidence MEDIUM): `local` 68 (54.4%) · `clause_level` 42 (33.6%) · `sentence_level` 9 (7.2%) · `cross_clause` 6 (4.8%).

**Use for difficulty control** — but with an explicit caveat: in this dataset, `local` errors trend toward lower `error_detectability` values (easier to find) and `cross_clause` errors trend toward higher values (harder to find). This is a **directional tendency observed in the data**, not a strict rule; do not mechanically assume every `cross_clause` error is HARD or every `local` error is EASY.

### 6.8 Correct answer position

**OBSERVED** (confidence HIGH):

| Position | count | % |
|---|---:|---:|
| A | 24 | 19.2% |
| B | 37 | 29.6% |
| C | 31 | 24.8% |
| D | 33 | 26.4% |

**DERIVED RULE:** Over a large generated corpus, error position should trend toward even across A–D.

**HEURISTIC:** The observed sample skews light on A (19.2%) and heavy on B (29.6%). When generating large batches, lean slightly toward more A-position errors than the raw observed ratio, to avoid compounding this skew — without forcing an exact 25% quota on small batches.

### 6.9 Sentence and clause characteristics

**OBSERVED** `sentence_word_count` (confidence HIGH): mean 20.05, median 20, min 10, max 33, stdev 4.27. Bins: 10–14: 11 · 15–19: 47 · 20–24: 50 · 25–29: 15 · 30–34: 2.

**OBSERVED** `clause_count` (confidence HIGH): 1: 59 (47.2%) · 2: 58 (46.4%) · 3: 8 (6.4%). Mean 1.59, median 2.

This is treated as an **independent distribution** from Structure's (§5.3–5.4): Written Expression skews toward slightly simpler clause structure (single- and two-clause sentences are nearly tied; three-plus-clause sentences are rarer here than in Structure), consistent with its format putting the complexity budget into "spot the local error" rather than "parse a complex clause."

**HEURISTIC:** For a 25-item batch: roughly 11–12 single-clause, 11–12 two-clause, 1–2 three-clause sentences; mean length near 20 words with occasional items up to ~30+ words.

### 6.10 Difficulty characteristics

**OBSERVED** (confidence MEDIUM):

| Metric (1–5 scale) | Mean | Distribution |
|---|---:|---|
| `syntactic_complexity` | 2.30 | 1=15, 2=61, 3=46, 4=3 (5 not observed) |
| `error_detectability` (1=easy, 5=hard) | 2.49 | 1=7, 2=60, 3=48, 4=10 (5 not observed) |
| `distractor_plausibility` | 2.48 | 1=6, 2=57, 3=58, 4=4 (5 not observed) |
| `estimated_difficulty_ai` | 2.30 | 1=18, 2=61, 3=37, 4=9 (5 not observed) |

> `estimated_difficulty_ai` is an AI structural estimate, **not** an ETS official difficulty rating (same caveat as §5.8).

**DERIVED RULE:** Control difficulty via `error_scope` (§6.7), error-detectability-relevant surface cues, and the plausibility of the 3 non-erroneous spans — not obscure vocabulary.

### 6.11 Vocabulary domain

**OBSERVED** (confidence MEDIUM): 112 unique `vocabulary_domain` values across 125 items. 9 domains repeat: `art history` (5), `astronomy` (3), and 7 domains appearing twice each (`anthropology`, `geology/earth science`, `literature/poetry`, `music`, `geology/mineralogy`, `literature/history`, `economics/history`); the remaining 103 domains appear once each.

**DERIVED RULE:** Generated Written Expression items should draw from a wide range of academic/general-interest domains, reproducing this observed *diversity* (higher raw domain count than Structure's, consistent with the larger 125-item batch size), not any specific observed domain list.

**HEURISTIC:** No fixed domain roster is mandated, and no single domain should be heavily overrepresented in a generated batch (the observed sample's single most-repeated domain, `art history`, still accounts for only 4.0% of items). As in Structure (§5.7), background/world knowledge must **never** be required to correct the erroneous portion — the flaw must be locatable using only the sentence's own grammar.

---

## 7. Item Generation Hard Rules

These rules are **binding** for any future Generator agent.

### 7.1 Shared (both sections)

1. Exactly four options / four marked portions per item.
2. Exactly one intended correct answer / one intended erroneous portion.
3. The answer must be defensible by standard written English grammar, unambiguously.
4. No specialized factual or world knowledge may be required to answer correctly.
5. Avoid semantic ambiguity that could create multiple acceptable answers.
6. Difficulty must primarily come from grammar/syntax, not vocabulary difficulty.
7. Do not reproduce or lightly paraphrase any ETS source item from the analyzed 200-item set.
8. Do not reuse distinctive proper nouns, numerical facts, or unusual wording found in source items.
9. Do not make the correct answer systematically the longest or most elaborately worded option.
10. Do not introduce unintended secondary grammatical errors anywhere in the item.

### 7.2 Structure-specific

1. The blank, once filled with the correct option, must produce one complete, grammatically well-formed sentence with no other errors.
2. All three distractors must be traceable to one of the 15 `tested_error_type` mechanisms (§3.2).
3. No distractor may be correct under any plausible reading of the sentence (no accidental double-correct answers).
4. The sentence must stand alone — no external passage or context required.

### 7.3 Written-Expression-specific

1. The sentence, once the erroneous portion is corrected, must be entirely free of grammatical errors.
2. Exactly one of the four marked portions may be wrong; the other three must be independently, unambiguously correct.
3. The erroneous portion's flaw must be locatable and correctable using only information inside the sentence.
4. Do not mark a portion as the error if fixing it would leave a different genuine error elsewhere in the sentence.

---

## 8. Anti-patterns

Failure modes to actively guard against in AI-generated items:

- Obviously broken / nonsensical distractors that no test-taker would plausibly select.
- Two options that are both independently defensible as correct.
- Testing obscure vocabulary knowledge rather than grammar knowledge.
- Conversational or informal sentence register (TOEFL ITP style is formal/academic).
- Unnatural, gibberish-sounding academic prose assembled just to hit a target word count.
- Every item in a batch having near-identical sentence length.
- Every HARD item using the same construction (e.g. always inversion).
- Correct answers concentrated only in B/C across a batch, systematically avoiding A/D.
- A Written Expression sentence containing two genuine grammatical errors (only one may be intended).
- An underlined/marked error identifiable without reading the rest of the sentence (detectable in isolation).
- Distractors differing from the correct answer only by random word-order scrambling with no coherent pedagogical rationale (i.e. not tied to a real `tested_error_type` mechanism).
- Reusing a source item's distinctive subject matter, named entity, date, or statistic even when the wording is changed.

---

## 9. Batch-level Generation Blueprint

**Status: HEURISTIC.** Example batch sizes: **15 Structure items**, **25 Written Expression items** (matching one official test's item counts per section).

Controls to apply **at the batch level**, not per-item:

- **primary_target diversity** — spread across multiple categories, informed by §5.2 / §6.2 guidance ranges, not a single repeated category.
- **answer-position balance** — avoid systematic skew toward any one of A–D across the batch.
- **sentence-length diversity** — mix of short/medium/long items matching the observed distribution shape (§5.3 / §6.9).
- **clause-count diversity** — mix of 1/2/3+ clause items matching the observed distribution shape (§5.4 / §6.9).
- **topic/vocabulary-domain diversity** — avoid repeating the same domain more than 1–2 times per batch (§5.7).
- **difficulty diversity** — a mix of EASY/MEDIUM/HARD per §4, not all-same-difficulty.
- **error-type diversity** (`tested_error_type` / distractor `error_type`) — spread across multiple mechanisms, favoring but not limited to the dominant observed ones (§5.5 / §6.3).

**Explicit non-goal:** do not attempt to exactly reproduce the observed 75-item / 125-item distributions in every batch. The observed distributions are a center of gravity, not a per-batch checklist — reasonable batch-to-batch variance is expected and desirable.

**Illustrative difficulty split (HEURISTIC, proportional to observed `estimated_difficulty_ai` tiers):**

- 15-item Structure batch: ≈4 easy / 8 medium / 3 hard.
- 25-item Written Expression batch: ≈16 easy / 7 medium / 2 hard.

---

## 10. Taxonomy Holdouts

Three items in the 200-item source dataset remain flagged `taxonomy_issue: true` in the authoritative JSON — i.e., their current `primary_target` and/or `tested_error_type` classification is a documented best-fit approximation rather than a clean match, because each is a **single-instance, unresolved pattern** that did not clear the "recurs 3+ times across multiple Practice Tests" bar for promotion to a new taxonomy category (see `GRAMMAR_TAXONOMY_CHANGELOG.md` for the promotion criteria that *were* applied to add `WORD_CLASS_FORM`, `wrong_preposition_collocation`, and `wrong_degree_form` in v1.1).

**Three single-instance unresolved taxonomy holdouts exist** (source IDs, no item content reproduced here): one item in Practice Test D, one in Practice Test E, and one in Practice Test F.

**DERIVED RULE:** Do not create a new generation category, `primary_target`, or `tested_error_type` value based on these 3 holdout items. They are noted for completeness only and should not influence generation.

---

## 11. Copyright and Source Separation

**Principle:** This specification describes **abstract item-design features** distilled from ETS TOEFL ITP items. It does not itself contain, quote, or closely paraphrase ETS item text.

**Binding constraints for any future Generator:**

1. Do not copy sentences or sentence fragments from any of the 200 analyzed source items.
2. Do not lightly paraphrase (synonym-swap) a source item while preserving its structure/content.
3. Do not reuse distinctive phrases, named entities, dates, or statistics from source items.
4. Do not reproduce the same combination of person + fact + number found in a source item, even with different wording.
5. Every generated item must be an independently authored sentence built from this specification's abstracted design features — not derived from any specific source item.

---

## 12. Machine-readable Constraint Summary

A compressed cross-reference only — the detailed specification in §5–§8 above is authoritative; do not treat this summary as a substitute for it. The full machine-readable version lives in `specs/toefl_itp_grammar_spec.json`.

```yaml
STRUCTURE:
  options: 4
  correct_answers: 1
  taxonomy_version: "1.1"
  primary_target_categories: 15
  tested_error_type_values: 15
  sentence_word_count_range_observed: [10, 27]
  sentence_word_count_mean_observed: 19.97
  clause_count_range_observed: [1, 4]
  clause_count_mode: 2
  correct_answer_position_observed_pct: { A: 24.0, B: 28.0, C: 26.7, D: 21.3 }

WRITTEN_EXPRESSION:
  marked_parts: 4
  erroneous_parts: 1
  taxonomy_version: "1.1"
  primary_target_categories: 15
  tested_error_type_values: 15
  sentence_word_count_range_observed: [10, 33]
  sentence_word_count_mean_observed: 20.05
  clause_count_range_observed: [1, 3]
  clause_count_mode: 2
  correct_answer_position_observed_pct: { A: 19.2, B: 29.6, C: 24.8, D: 26.4 }
  fragment_error_type_possible: false
```

---

## Appendix: Document provenance

- Built from `analysis/GRAMMAR_TAXONOMY.md`, `analysis/grammar_taxonomy.json` (v1.1), `analysis/GRAMMAR_TAXONOMY_CHANGELOG.md`, `analysis/structure_items_all.{json,csv}`, `analysis/STRUCTURE_ANALYSIS_REPORT.md`, `analysis/written_expression_items_all.{json,csv}`, `analysis/WRITTEN_EXPRESSION_ANALYSIS_REPORT.md`, `analysis/taxonomy_issues_structure.md`, `analysis/taxonomy_issues_written_expression.md`.
- All numeric values were independently recomputed from the JSON/CSV source files (not copied from the Markdown reports) as part of writing this specification, then cross-checked against the reports; no contradictions were found.
- This document supersedes no prior specification (none existed before this version).
