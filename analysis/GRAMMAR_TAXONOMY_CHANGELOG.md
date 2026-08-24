# GRAMMAR_TAXONOMY Changelog

Records changes to `analysis/GRAMMAR_TAXONOMY.md` / `analysis/grammar_taxonomy.json`, driven by
the taxonomy-gap review of Structure (75 items, `taxonomy_issues_structure.md`) and Written
Expression (125 items, `taxonomy_issues_written_expression.md`). Taxonomy version bumped
**1.0 → 1.1** on 2026-08-23.

## Decision criteria used

A new `primary_target` or `tested_error_type` value was added only if it satisfied at least one
(and in practice, for every addition below, several) of:

- **A.** Recurs across multiple Practice Tests (not just multiple items within one test).
- **B.** Forcing the phenomenon into an existing category clearly distorts that category's own
  definition.
- **C.** The distinction has independent value for controlling TOEFL ITP item generation later
  (i.e., a spec/generator would plausibly want to target this phenomenon on its own).
- **D.** The Reviewer confirmed the same force-fit workaround was independently used across
  multiple items/analyzers (a strong signal the gap is real, not an analyzer idiosyncrasy).

Single-instance phenomena (n=1) were **not** promoted to new categories/error types, even where
the force-fit was imperfect, per the explicit instruction to avoid over-fragmenting the taxonomy
for one-off cases. These remain flagged `taxonomy_issue: true` and are listed in "Reviewed, not
actioned" below.

---

## Change 1 — New `tested_error_type`: `wrong_preposition_collocation`

- **old taxonomy:** No `tested_error_type` value covered fixed lexical preposition/collocation
  errors. Every Analyzer independently force-fit these into `wrong_complementation`.
- **new taxonomy:** Added `wrong_preposition_collocation` (see `GRAMMAR_TAXONOMY.md` error_type
  table) — scoped to lexically-governed preposition/particle selection errors (verb+preposition,
  adjective+preposition, participle+preposition, noun+preposition) and standalone (non-governed)
  preposition/connector-pair choices, explicitly distinct from clause-structural complementation
  mismatches (`wrong_complementation`) and from logical-relation connector choice
  (`incorrect_subordinator`/`CONNECTORS_CONJUNCTIONS`).
- **reason:** Criteria A (all 5 Practice Tests), C (collocation-error generation is a distinct,
  controllable distractor strategy), D (13 analyzers/reviewer passes independently converged on
  the same `wrong_complementation` workaround with `taxonomy_issue: true`) all clearly met. This
  was the single most common taxonomy gap found across both phases (12 confirmed instances after
  re-review; see Change note below on the 2 items reclassified instead to `wrong_degree_form`).
  `primary_target` routing (`VERB_COMPLEMENTATION` for verb/participle/adjective-governed cases,
  `CONNECTORS_CONJUNCTIONS` for standalone/non-governed cases) was kept as the existing Reviewer
  precedent already established — only `tested_error_type` changed, since that routing distinction
  (is a specific word governing the preposition, or not) is itself meaningful and worth preserving.
- **affected items (12):** all previously `wrong_complementation` + `taxonomy_issue: true`, all
  reclassified to `wrong_preposition_collocation` + `taxonomy_issue: false`:
  - Test B: Q18 ("instead than" vs "rather than"), Q33 ("benefit from" vs "benefit of"),
    Q36 ("during...until" vs "from...until")
  - Test C: Q21 ("paintings of" vs "onto"), Q27 ("beside" vs "between")
  - Test D: Q19 ("varies from...to"), Q31 ("given to" vs "into"), Q37 ("known for" vs "known as")
  - Test E: Q21 ("found in/at"), Q36 ("associated with" vs "associated by")
  - Test F: Q27 ("rich in" vs "rich of"), Q29 ("related to" vs "related for")
- **affected tests:** B, C, D, E, F (all 5) — Written Expression only; Structure had no
  corresponding items (Structure's Part A format does not surface fixed-collocation distractors in
  the same way).

## Change 2 — New `tested_error_type`: `wrong_degree_form`

- **old taxonomy:** No `tested_error_type` value covered comparative/superlative degree confusion
  or degree-intensity-marker misselection. The Structure phase force-fit its one instance into
  `incorrect_part_of_speech`; the Written Expression phase force-fit its two instances into
  `wrong_complementation`.
- **new taxonomy:** Added `wrong_degree_form` — scoped to (a) comparative/superlative/positive
  degree-form confusion, and (b) degree/intensity-marker selection for a construction that
  requires a specific marker (e.g. "so...that" vs "very...that").
- **reason:** Individually, the Structure instance (n=1) and the two Written Expression instances
  (n=2, but both "so"/"very" confusion, a narrower sub-pattern than the Structure instance's
  comparative/superlative confusion) each fall short of the "3+ across tests" bar on their own.
  However, both are members of the same broader family — degree/intensity-marker misselection in
  a comparative-adjacent construction — and together span 3 different Practice Tests (Structure
  Test E; Written Expression Tests C and F). The Written Expression Reviewer's own review
  (`taxonomy_issues_written_expression.md` §6) explicitly considered and rejected merging these
  two sub-patterns into one category; this coordinator-level review reconsiders that call and
  judges them close enough in kind (both are "which degree/intensity form does this construction
  require" errors, criterion B: `incorrect_part_of_speech` and `wrong_complementation` both
  meaningfully mischaracterize what's actually wrong) and valuable enough to control independently
  in future generation (criterion C: comparative-vs-superlative and so-vs-very are both classic,
  well-defined TOEFL distractor patterns) to justify one shared `tested_error_type`. This is a
  judgment call, flagged here explicitly for visibility; the two sub-patterns remain
  distinguishable via `subtype` text.
- **affected items (3):**
  - Structure Test E, Q9, distractor A: `error_type` `incorrect_part_of_speech` →
    `wrong_degree_form` (comparative-for-superlative confusion in a correlative comparative
    construction). No item-level `taxonomy_issue` flag existed for this distractor-level field in
    the Structure schema, so no flag change was needed there.
  - Written Expression Test C, Q37: `tested_error_type` `wrong_complementation` →
    `wrong_degree_form`, `taxonomy_issue: true` → `false` ("very" used where "so" is required to
    license the following result clause).
  - Written Expression Test F, Q31: same fix, same reason (identical construction).
- **affected tests:** Structure Test E; Written Expression Tests C, F.

## Change 3 — New `primary_target`: `WORD_CLASS_FORM`

- **old taxonomy:** No `primary_target` named "wrong derivational form / part of speech for a
  given syntactic slot." Depending on which slot the error occurred in, Analyzers force-fit these
  items into three different existing categories: `WORD_ORDER_MODIFICATION` (for NP-internal
  modifiers/head nouns — 8 items after including one previously-undocumented case, see below),
  `VERB_COMPLEMENTATION` (for verb-modifying adverbials — 3 items), and `CLAUSE_STRUCTURE` (for a
  word-class error in subject position — 1 item).
- **new taxonomy:** Added `WORD_CLASS_FORM` (15th `primary_target`, at the practical ceiling) —
  covers derivational/part-of-speech form selection (adjective/adverb/noun/verb) for a single word
  in any syntactic slot, when the error is not about element ordering, verb complementation, or
  clause well-formedness as such.
- **reason:** This was the clearest, best-evidenced case for a genuinely new category rather than
  a definition tweak. Criterion A is met strongly (11 confirmed items — 12 counting one
  previously-undocumented case — spanning all 5 Practice Tests, both Structure-analogous and
  Written-Expression-only patterns). Criterion B is met unambiguously: `WORD_ORDER_MODIFICATION`'s
  own definition is explicitly about element *ordering*, not word *class*; `VERB_COMPLEMENTATION`
  is explicitly about *complement* structure (a required argument), not optional adverbial
  modification; `CLAUSE_STRUCTURE` is about clause well-formedness, not word-class choice within an
  already-well-formed clause. Splitting the same underlying phenomenon (wrong derivational form)
  across three semantically unrelated categories directly violated this project's own standing
  principle that the same grammatical phenomenon should map to the same `primary_target` across
  both sections (Step 4 instructions, and Reviewer checklist item 7 of this review). Criterion C is
  met: part-of-speech/derivational-form confusion is already the single most common
  `tested_error_type` in Written Expression (`incorrect_part_of_speech`, 28.0% of all items before
  this review) and having no dedicated `primary_target` "home" for it was a structural gap worth
  closing before spec-writing. Criterion D is met (multiple analyzers independently converged on
  the same three-way force-fit).
- **affected items (12):** all reclassified to `WORD_CLASS_FORM`, `taxonomy_issue: true` → `false`:
  - From `WORD_ORDER_MODIFICATION` (8): Test B Q30 ("recent" vs "recently"), Q34 ("fifteen
    century" vs "fifteenth" — cardinal/ordinal number form; this item was **not** listed in
    `taxonomy_issues_written_expression.md`'s Issue #3 write-up despite matching the identical
    pattern — a documentation gap in the original Reviewer pass, corrected here); Test D Q16
    ("listener" vs "listen"), Q17 ("good" vs "well"), Q22 ("complex" vs "complexity"), Q40 ("local"
    vs "locally"); Test F Q17 ("rapid" vs "rapidly"), Q19 ("region" vs "regional")
  - From `VERB_COMPLEMENTATION` (3): Test B Q40 ("intentional" vs "intentionally"), Test C Q31
    ("thorough" vs "thoroughly"), Test D Q26 ("rarity" vs "rarely")
  - From `CLAUSE_STRUCTURE` (1): Test E Q33 ("Hot" vs "Heat" as clause subject)
  - `tested_error_type` for all 12 remains `incorrect_part_of_speech` — unchanged, since that
    error-mechanism label was already correct; only `primary_target` was wrong.
- **affected tests:** B, D, E, F (all Written Expression). No Structure items were reclassified —
  a systematic check of all Structure `distractors.*.error_type == incorrect_part_of_speech`
  instances (11 total) found none where the item's own `primary_target` (i.e. the *correct
  answer's* tested construction, not a distractor's error mechanism) was itself a word-class-form
  question; Structure's format does not appear to surface this pattern at the item level the way
  Written Expression's error-identification format does.

## Reviewed, not actioned (kept as single-instance `taxonomy_issue: true`)

Per the decision criteria, these remain flagged rather than promoted, since each is a single
confirmed instance in one test only (criterion A not met) and none forces a large definitional
distortion severe enough to independently justify a new category (criterion B borderline at best):

- **Written Expression Test E, Q20** — coordinating-conjunction substitution ("and" for "but" in a
  "not X but Y" contrast). Force-fit remains `CONNECTORS_CONJUNCTIONS` / `incorrect_subordinator`.
  Worth watching for recurrence in future test analyses (a plausible common ETS distractor pattern
  generally, even though only 1 instance appears in this 200-item sample).
- **Written Expression Test D, Q34** — lexical adjective substitution ("near" vs "next" in a
  future-time expression). Not a part-of-speech confusion (both words are adjectives), so it does
  **not** belong in `WORD_CLASS_FORM` despite superficial similarity. Force-fit remains
  `REFERENCE_AND_DETERMINERS` / `incorrect_part_of_speech`.
- **Written Expression Test E, Q18** — idiomatic prepositional-phrase collocation at the phrase
  level ("years of age" vs "of old"). Distinct from Change 1's `wrong_preposition_collocation`
  pattern (the preposition itself, "of," is not what's wrong here — the following idiom word is).
  Force-fit remains `VERB_COMPLEMENTATION` / `incorrect_part_of_speech`.
- **Written Expression Test F, Q30** — extraneous adverb wedged inside a participial phrase.
  `tested_error_type` (`extraneous_element`) is already exactly correct; only `primary_target`
  (`NONFINITE_VERB_PHRASES`) is a loose fit, with no closer existing category. Left unchanged.

## Re-evaluated to `taxonomy_issue: false` without any taxonomy change

- **Written Expression Test F, Q24** — bare-plural noun required by real-world semantic plurality
  ("women nurse" vs "women nurses"), previously flagged `taxonomy_issue: true`. On re-review, this
  is judged a legitimate (if slightly novel) subtype of the already-well-established
  `REFERENCE_AND_DETERMINERS` / `agreement_error` pattern — that category's own definition
  explicitly includes "quantifier agreement with countable/uncountable noun," and plural-marking
  driven by real-world plurality is a reasonable extension of the same concept, not a genuine
  vocabulary gap. No category or error_type change; `taxonomy_issue` flipped `true` → `false`,
  `taxonomy_issue_reason` cleared to `null`.

## Net effect on `taxonomy_issue` counts (Written Expression)

| | before | after |
|---|---:|---:|
| `taxonomy_issue: true` | 31 / 125 | 4 / 125 |
| `taxonomy_issue: false` | 94 / 125 | 121 / 125 |

The 4 remaining `true` items are exactly the four "Reviewed, not actioned" items listed above
(E20, D34, E18, F30).

## Taxonomy size after this update

- `primary_target`: 14 → **15** (added `WORD_CLASS_FORM`; still within the documented 10-15
  range, now at the practical ceiling).
- `tested_error_type` / distractor `error_type`: 13 → **15** (added
  `wrong_preposition_collocation`, `wrong_degree_form`). This vocabulary was previously only
  defined implicitly in generation prompts and is now formally documented in
  `GRAMMAR_TAXONOMY.md` / `grammar_taxonomy.json` for the first time.
- `grammar_taxonomy.json` version: **1.0 → 1.1**.
