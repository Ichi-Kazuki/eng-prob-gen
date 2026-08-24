# Taxonomy Issues — Structure (Part A) Review

Findings from the consistency review of `structure_test_B.json` through `structure_test_F.json`
(75 items total) that point to a possible gap in the taxonomy itself, as opposed to a simple
mislabeling that could be corrected in place. Per review instructions, `GRAMMAR_TAXONOMY.md` and
`grammar_taxonomy.json` were left untouched; this file only records the observation and a
non-binding suggestion for future evolution of the taxonomy.

## 1. No `error_type` value covers "wrong degree form" (comparative vs. superlative confusion)

**Affected item:** Practice Test E, Q9, distractor A (`structure_test_E.json`).

**Phenomenon:** The item tests the correlative comparative construction "the + comparative...,
the + comparative..." ("the greater the distance..., the [comparative] ..."). Distractor A
substitutes the superlative form for the required comparative form — a "wrong degree" error
(comparative vs. superlative), not a part-of-speech error in the usual sense (the word is still
an adjective; only its degree/morphology is wrong).

**Why existing categories don't fit well:** Of the 13 fixed `error_type` values, none names a
degree-form error directly. The Analyzer force-fit this into `incorrect_part_of_speech`, and the
item's own `error_explanation` originally carried an inline caveat acknowledging the mismatch
("...more precisely a wrong-degree-form error than a part-of-speech error, but no closer category
exists in the fixed vocabulary"). That caveat has been removed from the explanation text during
this review (analyst commentary shouldn't live in a field meant to explain the error to a learner),
but the underlying classification gap remains and is recorded here instead.

**Occurrence count:** Only one confirmed instance in this 75-item sample (Test E, Q9-A). This is
below the "2+ across different tests" bar normally used to justify a taxonomy write-up. It is
included anyway because (a) the Analyzer explicitly self-flagged it as a bad fit with no better
option available, and (b) comparative/superlative confusion is a common, well-established TOEFL
distractor pattern generally, so it is likely to recur once more Structure tests are analyzed —
worth watching rather than acting on immediately.

**Suggestion (not an implementation):** If this pattern recurs 1–2 more times in future test
analyses, consider adding a 14th `error_type` value such as `wrong_degree_form` (or
`incorrect_comparative_degree`) to the fixed 13-value vocabulary, scoped specifically to
comparative/superlative/positive degree confusion in adjectives and adverbs — distinct from
`incorrect_part_of_speech`, which should stay reserved for actual part-of-speech substitutions
(e.g., noun for adjective, adverb for adjective).

## Notes on other borderline calls (resolved without a taxonomy-level issue)

For completeness, the other borderline calls flagged in the review brief were resolved as follows
and did **not** warrant a taxonomy-file change or an entry above:

- **Test C Q2** (`continues to create`) and **Test E Q2** (`begin to V`): `NONFINITE_VERB_PHRASES`
  is correct — the taxonomy's own `example_subtypes` for that category explicitly list "gerund vs.
  infinitive complement selection," and both items use this consistently.
- **Test C Q11** (relative clause with "where" + elliptical passive): kept as `RELATIVE_CLAUSES`.
  None of its distractors test tense/voice *selection* (no active-vs-passive choice is offered);
  they test whether the clause has a complete, correctly-ordered subject+verb, which is squarely
  `RELATIVE_CLAUSES` territory as used consistently elsewhere in the dataset.
- **Test D Q10** ("such materials as...") was reclassified from `COMPARATIVES_DEGREE` to
  `CONNECTORS_CONJUNCTIONS` to match the parallel exemplification-connector item in Test F Q7
  ("such as"). This was a direct fix, not a taxonomy gap (see main review report).
- **Test F Q4** (it-cleft "It was X that..."): kept as `CLAUSE_STRUCTURE`. Although
  `EXISTENTIAL_EXPLETIVE` explicitly covers expletive "it + be," none of this item's distractors
  contest the expletive subject itself (no swap for a wrong pronoun/determiner, unlike the
  `EXISTENTIAL_EXPLETIVE` items in Tests B/C/E); all distractors are non-finite fragments versus
  the cleft's finite verb, which matches the dominant cross-test pattern for `CLAUSE_STRUCTURE`
  main-clause-identification items.
- **Test F Q1 and Q6**: Q1 was kept as `WORD_ORDER_MODIFICATION` (all distractors are pure
  word-order permutations of the same lexical items — no complementation choice is at stake). Q6
  was reclassified from `WORD_ORDER_MODIFICATION` to `VERB_COMPLEMENTATION` (direct fix — its own
  `correct_answer_reason` identifies it as a predicate nominative after "is the," matching the
  established `VERB_COMPLEMENTATION` pattern in Tests B/C/E Q1, and none of its distractors are
  word-order permutations).
