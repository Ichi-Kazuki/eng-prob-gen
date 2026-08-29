---
name: toefl-itp-reading-generator-v0.2.6
description: Original variable-length TOEFL ITP-style Reading Comprehension set generator
version: v0.2.6
tools: Read
---

# Reading Comprehension Generator v0.2.6

Generate one original academic expository passage and its complete question
set. The deterministic plan in the task input is authoritative: use the
domain, target word count, paragraph target as guidance, `question_count`, and
the exact `question_type_counts` multiset. The legacy ordered `question_plan`
is retained for compatibility only; the trusted pipeline owns final
evidence-position-aware ordering.

Requirements:

- For passage realization, treat target_words as a real writing target, not a loose suggestion. Normally remain close to target_words, using a soft tolerance on the order of a few dozen words calibrated to observed realization error; this is not an exact hard count, and slight differences do not by themselves invalidate the passage. Avoid adding extra examples, background, concluding exposition, or paragraph padding merely to make the passage richer or fill space. Preserve completeness and naturalness. Never truncate a sentence unnaturally just to hit target_words. Existing validity behavior is unchanged: below 160 words is hard-invalid, 160-300 words is the empirical preferred band, and above 300 words is an empirical warning rather than a hard rejection.
- Write original content. Do not quote, reproduce, lightly paraphrase, or imitate any official ETS or practice-test passage or question.
- Generate semantic content only. Do not emit `passage_id` or question `item_id`; trusted pipeline code attaches those deterministic identity fields after generation. Do not put the domain or title in those IDs.
- Produce exactly `question_count` questions in one response and one invocation. The model-facing schema provides `detail_questions`, `vocabulary_in_context_questions`, `inference_questions`, `main_idea_questions`, and `reference_questions` collections. Put exactly the requested number in each type-specific collection, including an empty array for a zero quota; together they must exactly match `question_count` and `question_type_counts`. Do not emit a flat `questions` array or attempt to reproduce a cross-type order; trusted pipeline code orders the flattened questions by passage evidence position after generation.
- Give every question exactly four non-empty, distinct choices labeled A, B, C, and D.
- Make exactly one choice defensibly correct and make the item answerable from the passage.
- If the plan contains `difficulty_profile`, treat it as a structural calibration target, not as a request for arbitrary hardness. Keep lexical and syntactic load at moderate academic levels; do not manufacture difficulty with obscure terminology, unnecessary sentence embedding, or trick logic. Create difficulty primarily through meaning-preserving paraphrase, appropriate evidence integration, genuine supported inference when the planned type calls for it, and plausible text-grounded distractors. `MIX_LOCAL_AND_DISTRIBUTED_WHEN_NATURAL` means use distributed evidence only when the passage genuinely supports it; never force cross-idea reasoning just to satisfy the profile. The profile is a provisional structural proxy and never implies TOEFL ITP score equivalence.
- For INFERENCE questions, the keyed answer must not be explicitly stated in the passage and must not be obtainable merely by replacing words in one passage sentence with synonyms or a close paraphrase. Before emitting each INFERENCE item, silently test: 'If I can point to one passage sentence whose meaning directly states the correct option, even with ordinary synonym substitution, this is not a valid inference question.' If yes, rewrite the inference item rather than labeling the paraphrase as INFERENCE. Do not expose this internal check in generated question text or metadata unless the existing schema supports an appropriate field. A valid inference must require at least one reasoning step from the passage, such as an implication, consequence, likely condition, causal relationship, comparison, purpose, relationship between ideas, or conclusion supported but not directly stated. Local inference is allowed when one sentence or adjacent sentences support a genuinely unstated implication. Cross-idea inference is allowed when separated or multiple passage ideas naturally support the conclusion. Do not manufacture unnecessary multi-sentence complexity or force cross-idea reasoning. Every inference must remain fully supported by the passage and fully entailed by the text, with one unique defensible answer; it must be uniquely answerable, conservative, and free of outside knowledge; unsupported or ambiguous inference is worse than a shallow inference. Do not create difficulty through simple negation/reversal or artificial logical tricks. Distractors should be plausible but not entailed.
- Separate distinct passage paragraphs with a blank line (`\n\n`), and do not treat a single LF as a canonical paragraph break. Evidence paragraph numbers must correspond exactly to the canonical paragraphs separated by blank lines. Treat paragraph count as guidance only, not as a new hard quota; do not introduce a fixed paragraph-count quota.
- Treat `question_type` as the empirical primary planning category and include a secondary `subtype` for every question. Use `DIRECT_FACTUAL_DETAIL`, `PARAPHRASED_FACTUAL_DETAIL`, or `NEGATIVE_EXCEPT_DETAIL` for DETAIL; `LOCAL_INFERENCE`, `CROSS_IDEA_INFERENCE`, or `RHETORICAL_PURPOSE` for INFERENCE; `VOCABULARY_CONTEXT_MEANING` for VOCABULARY_IN_CONTEXT; `PASSAGE_MAIN_IDEA` for MAIN_IDEA; and `ANTECEDENT_REFERENCE` for REFERENCE. These subtypes describe item behavior only; do not infer or invent subtype frequencies that are not measured in the empirical profile. Rhetorical-purpose stems may ask why the author mentions or discusses something, or the purpose of an example.
- For every question include private `distractor_metadata` for A/B/C/D. Mark the keyed choice `CORRECT_OPTION` and give each wrong choice one plausible error mechanism plus a short rationale. Use only mechanisms that fit the item, such as `TEXT_TRUE_BUT_NOT_ANSWER`, `WRONG_REFERENT`, `SCOPE_SHIFT`, `CAUSE_EFFECT_REVERSAL`, `OVERGENERALIZATION`, `UNDERGENERALIZATION`, `LEXICAL_SENSE_TRAP`, `UNSUPPORTED_INFERENCE`, `NEARBY_DETAIL_CONFUSION`, or `CONTRADICTED_BY_PASSAGE`. Do not force a category, use outside knowledge, or make distractors silly. This metadata is private QA information and must never appear in blind inputs.
- For VOCABULARY_IN_CONTEXT questions, both ordinary dictionary senses and
  context-clarified senses are acceptable, but prefer a word whose actual
  local sentence disambiguates among multiple plausible general-English
  senses. Do not require strong context dependence for every item and do not
  choose obscure vocabulary merely to increase difficulty. The tested word
  must occur naturally in the passage, not look inserted solely for the item.
  The keyed synonym must match the target word's actual sense in its local
  sentence. When a target word is polysemous, distinguish between legitimate
  dictionary senses using grammatical construction, collocation, and local
  context. Distractors may use other legitimate dictionary senses when those
  senses are wrong in the sentence. The rationale must explain why the keyed
  sense fits the local usage.
- For VOCABULARY_IN_CONTEXT and REFERENCE questions, use conventional line-based
  wording such as `The word 'X' in line N is closest in meaning to` or `The word
  'it' in line N refers to`. Include private `target_text` and 1-based global
  `target_line` metadata. The trusted display model uses Unicode NFC,
  whitespace normalization, and a fixed 72-character word wrap; do not place
  line numbers into the passage text.
- Use the selected academic domain as a topic anchor for a self-contained
  expository passage, with enough definitions, examples, contrasts, causal
  links, chronology, and references to support the planned questions. Keep the
  register like compact academic textbook prose, avoid unsupported specialist
  jargon, do not make every passage STEM-oriented, and do not write
  controversial current-affairs or opinion commentary.
- Keep correct options from being systematically the longest or most specific.
  Give distractors comparable grammatical form and approximate information
  density. Do not pad options merely to equalize character counts; preserve
  semantic quality when exact lengths differ naturally.
- For each question, provide the intended answer and private evidence metadata. The evidence paragraph is one-based and its anchor must be an exact phrase from that paragraph. The rationale is internal QA metadata. For target questions, the target line and target text must agree with the stem and the displayed passage line.
- Use natural academic English and conventional TOEFL ITP-style wording. Do not include markdown, answer explanations outside the schema, or commentary.

Return only one JSON object matching the supplied v0.2.2 grouped semantic Generator output schema.
