# Taxonomy Issues — Written Expression (Part B) Review

Findings from the consistency review of `written_expression_test_B.json` through
`written_expression_test_F.json` (125 items total) that point to a possible gap in the taxonomy
itself, as opposed to a simple mislabeling that could be corrected in place. Per review
instructions, `GRAMMAR_TAXONOMY.md` and `grammar_taxonomy.json` were left untouched; this file
only records the observations and non-binding suggestions for future evolution of the taxonomy.
Direct mislabelings found during the same review were fixed in place and are listed in the
reviewer's final report rather than here.

## 1. No `tested_error_type` value covers "wrong preposition/collocation"

**Affected items (14, across all five tests):** `written_expression_test_B.json` Q18, Q33, Q36;
`written_expression_test_C.json` Q21, Q27, Q37; `written_expression_test_D.json` Q19, Q31, Q37;
`written_expression_test_E.json` Q21, Q36; `written_expression_test_F.json` Q27, Q29, Q31.

**Phenomenon:** A fixed lexical collocation between a verb/participle/adjective and its
preposition (or between two paired prepositions/connectors) is violated — e.g. "benefit from" vs
"benefit of," "associated with" vs "associated by," "rich in" vs "rich of," "known for" vs "known
as," "varies from...to" vs "varies to...to," "during...until" vs "from...until," "beside" vs
"between." None of these are complement-structure errors (no clause/phrase-type mismatch) and
none are connector-word-choice-among-logical-relations errors in the `CONNECTORS_CONJUNCTIONS`
sense (cause/contrast/comparison); they are pure lexical-collocation slips.

**Why existing categories don't fit well:** Of the 13 fixed `tested_error_type` values, none
names a preposition/collocation error directly. Every Analyzer independently converged on
`wrong_complementation` as the closest-available `tested_error_type` and self-flagged
`taxonomy_issue: true` with a reason acknowledging the gap. During this review, two items
(`written_expression_test_E.json` Q36 and `written_expression_test_F.json` Q31) had the identical
collocation-substitution pattern as sibling items elsewhere but had been left with
`taxonomy_issue: false`; both were corrected to `true` with a matching reason as a direct fix
(not a taxonomy change), since the underlying gap and workaround are already established
practice across the dataset.

**Secondary `primary_target` question:** for the verb/participle/adjective-governed subset (e.g.
"benefit from," "associated with," "rich in," "related to," "found in/at," "given to," "known
for," "varies from...to"), `VERB_COMPLEMENTATION` (broadened beyond its literal
linking-verb/causative-verb definition) is the closest `primary_target` fit and is now used
consistently for all such items after this review's fixes (three `written_expression_test_D.json`
items — Q19, Q31, Q37 — were reclassified from `CONNECTORS_CONJUNCTIONS` to `VERB_COMPLEMENTATION`
to match this pattern; see the reviewer's final report). For the non-verb-governed subset (e.g.
"instead than/rather than," "during...until," "beside/between" — standalone prepositions or
connector phrases not selected by a specific governing verb), `CONNECTORS_CONJUNCTIONS` remains
the closest fit and was left unchanged.

**Occurrence count:** 14 confirmed instances across all five tests — well above the "3+ across
tests" bar the Structure-phase taxonomy doc sets for considering a new category. This is the
single most common taxonomy gap observed in the Written Expression phase.

**Suggestion (not an implementation):** Add a 14th `tested_error_type` value such as
`wrong_preposition_collocation` (or `wrong_collocation`) to the fixed 13-value vocabulary, scoped
to lexically-governed preposition/particle selection errors (verb+preposition, adjective+
preposition, noun+preposition, and paired-preposition/connector idioms) that are not clause-
structural complementation errors and not logical-relation connector-word choices. If adopted,
consider whether a companion `primary_target` (e.g. a broadened `VERB_COMPLEMENTATION` scope
statement, or a new `PREPOSITIONAL_COLLOCATION` category) is also warranted, since 12 of the 14
items above are currently split across `VERB_COMPLEMENTATION` and `CONNECTORS_CONJUNCTIONS` by
"which word governs the preposition" rather than by any category the taxonomy doc actually
defines.

## 2. No `tested_error_type` value covers "wrong coordinating conjunction"

**Affected item:** `written_expression_test_E.json` Q20 ("not in war...and in peace" — should be
"but").

**Phenomenon:** A negated first element ("not X") requires the contrastive coordinator "but" to
introduce the second element; the additive coordinator "and" is used instead. This is a
coordinating-conjunction substitution, not a subordinating-conjunction/preposition confusion (the
pattern that `incorrect_subordinator` is used for elsewhere, e.g.
`written_expression_test_D.json` Q38 "Despite" vs "Although" and
`written_expression_test_F.json` Q32 "if" vs "during").

**Why existing categories don't fit well:** The Analyzer force-fit this into
`incorrect_subordinator` (the closest available value, since "and"/"but" are conjunctions) and
self-flagged `taxonomy_issue: true` with a reason acknowledging that no `tested_error_type` value
actually names coordinator substitution. This review found the flag and reasoning already
correctly applied; no fix was needed.

**Occurrence count:** Only one confirmed instance in this 125-item sample — below the normal bar
for a new category, but noted here since it is a distinct phenomenon from both the preposition-
collocation gap above and the correctly-fitting `incorrect_subordinator` cases, and coordinator
substitution ("and" for "but," "or" for "nor," etc.) is a plausible recurring TOEFL distractor
pattern worth watching for in future test analyses.

## 3. No `primary_target` covers part-of-speech confusion for a single noun-phrase-internal modifier

**Affected items (7):** `written_expression_test_B.json` Q30 ("recent" vs "recently" modifying
"surge"); `written_expression_test_D.json` Q16 ("listener" vs "listen," head noun of a
prepositional object phrase — reclassified into this group during this review, see final report),
Q17 ("good" vs "well" modifying "sense"), Q22 ("complex" vs "complexity" modifying "process"), Q40
("local" vs "locally" modifying "tastes"); `written_expression_test_F.json` Q17 ("rapid" vs
"rapidly" modifying "drop"), Q19 ("region" vs "regional," head noun of a prepositional object
phrase).

**Phenomenon:** A single word occupies an attributive or head-noun position inside a noun phrase
(directly modifying a following noun, or serving as the head noun of a determined/prepositional
NP) but is the wrong part of speech (adjective needed but adverb/noun used, or noun needed but
adjective/verb used). None of these involve a parallel list (which would route to
`PARALLEL_STRUCTURE`), a predicate position after a linking verb (which would route to
`VERB_COMPLEMENTATION`), or a determiner/quantifier/pronoun (which would route to
`REFERENCE_AND_DETERMINERS`).

**Why existing categories don't fit well:** `WORD_ORDER_MODIFICATION` ("internal word order of
noun-modifying elements... noun phrase structure itself") is the closest available `primary_target`
and is now used consistently for all seven items above, but its own description is about *word
order*, not *word class*, so every one of these items self-flags `taxonomy_issue: true`. This
review confirmed the pattern is applied consistently across all three tests that exhibit it (B, D,
F) and made one direct fix (`written_expression_test_D.json` Q16, previously misfiled under
`REFERENCE_AND_DETERMINERS`) to bring it in line with the other six.

**Occurrence count:** 7 confirmed instances across 3 of the 5 tests — comfortably above the "3+"
bar. This is the second most common taxonomy gap observed in the Written Expression phase.

**Suggestion (not an implementation):** Add a 15th `primary_target` such as
`NOUN_MODIFIER_FORM` (or extend `WORD_ORDER_MODIFICATION`'s definition to explicitly cover word-
class selection for noun-phrase-internal modifiers, not just their ordering) to give this
recurring pattern a definitionally accurate home.

## 4. No `primary_target` covers part-of-speech confusion for a single word modifying a verb (adverb required)

**Affected items (3):** `written_expression_test_B.json` Q40 ("intentionally" vs "intentional"
modifying "add"); `written_expression_test_C.json` Q31 ("thoroughly" vs "thorough" modifying
"understand"); `written_expression_test_D.json` Q26 ("rarely" vs "rarity" modifying "found").

**Phenomenon:** A single word modifies a verb (not a predicate-complement slot after a linking
verb) and requires the adverb form, but an adjective or noun form is used instead.

**Why existing categories don't fit well:** `VERB_COMPLEMENTATION` is the closest available
`primary_target` and is used consistently for all three items, cross-referenced explicitly in two
of the three `taxonomy_issue_reason` fields, but the category's own definition ("predicate
nominative/adjective... object complement") does not actually cover adverbial verb modification,
so all three self-flag `taxonomy_issue: true`. Confirmed consistent; no fix needed.

**Occurrence count:** 3 confirmed instances across 3 different tests — at the threshold the
Structure-phase doc uses for considering a new category, and structurally distinct from Issue #3
above (that issue is about modifiers *inside a noun phrase*; this one is about adverbial modifiers
of a verb elsewhere in the clause).

## 5. No `primary_target` names a derivational word-class error in subject position

**Affected item:** `written_expression_test_E.json` Q33 ("Heat" vs "Hot" as the clause subject —
"Hot expand, rise, and flow" needs a noun subject, not an adjective).

**Phenomenon:** The clause's subject slot requires a noun, but an adjective occupies it instead.
Unlike Issue #3 (a modifier inside someone else's noun phrase), this word *is* the head of its own
subject noun phrase with nothing else modifying it — the error is that the wrong part of speech
was chosen to fill the subject role itself.

**Why existing categories don't fit well:** `CLAUSE_STRUCTURE` ("whether an independent clause...
is correctly formed") is the closest fit, broadened to "subject well-formedness," and is
self-flagged `taxonomy_issue: true`. This review considered reclassifying this item to
`WORD_ORDER_MODIFICATION` to unify it with Issue #3, but concluded the two are structurally
different enough (subject-of-clause vs. modifier/head-noun-inside-an-NP) that forcing them into
the same bucket would not actually resolve the underlying gap, so the item was left unchanged.

**Occurrence count:** Only one confirmed instance — below the normal bar for a new category, and
recorded here for visibility rather than as an action item.

## 6. Cross-reference: Structure-phase's `wrong_degree_form` gap

The Structure-phase review (`taxonomy_issues_structure.md`) flagged one item (Test E, Q9-A) where
a comparative/superlative degree-form confusion had no dedicated `tested_error_type` and was
force-fit into `incorrect_part_of_speech`. This Written Expression review did **not** find an
analogous pure comparative-vs-superlative degree-form error among the 125 items (the closest
related items — `written_expression_test_B.json` Q24 "most lowest," a double-superlative
redundancy correctly tagged `extraneous_element`, and the "so...that" vs "very...that" items in
Issue #1's `wrong_complementation` group — are different phenomena). No action taken; recorded
here per the review brief's instruction to cross-reference, and worth continuing to watch for if
more ETS practice tests are analyzed in the future.

## Notes on other borderline calls (resolved without a taxonomy-level issue)

- **`written_expression_test_F.json` Q30** ("starring together Humphrey Bogart" — extraneous
  adverb wedged between a participle and its direct object): filed under `NONFINITE_VERB_PHRASES`
  with `taxonomy_issue: true`, self-flagged as "really an extraneous-element/word-order issue
  rather than a form-selection one." The `tested_error_type` (`extraneous_element`) is exactly
  right; only the `primary_target` is a loose fit, and no better category exists (it is not a
  noun-phrase-internal modifier, so it does not belong with Issue #3). Left unchanged; not
  common enough (1 instance) to warrant a category proposal.
- **`written_expression_test_F.json` Q24** ("women nurse" vs "women nurses" — plural required by
  real-world semantics rather than by an explicit quantifier/numeral/article trigger): filed
  under `REFERENCE_AND_DETERMINERS` with `taxonomy_issue: true`, self-flagged as an imperfect fit.
  Left unchanged; this is a minor variant of the well-established quantifier-agreement pattern
  already used consistently across dozens of other items in this category (numerals, "several,"
  "a swarm of," "one of the," etc.), just without an overt quantifier word, so it does not rise to
  a distinct gap.
