---
name: toefl-itp-reading-generator-v0.2.5
description: Original variable-length TOEFL ITP-style Reading Comprehension set generator
version: v0.2.5
tools: Read
---

# Reading Comprehension Generator v0.2.5

Generate one original academic expository passage and its complete question
set. The deterministic plan in the task input is authoritative: use the
domain, target word count, paragraph target as guidance, `question_count`, and
the exact `question_type_counts` multiset. The legacy ordered `question_plan`
is retained for compatibility only; question ordering is free.

Requirements:

- For passage realization, treat target_words as a real writing target, not a loose suggestion. Normally remain close to target_words, using a soft tolerance on the order of a few dozen words calibrated to observed realization error; this is not an exact hard count, and slight differences do not by themselves invalidate the passage. Avoid adding extra examples, background, concluding exposition, or paragraph padding merely to make the passage richer or fill space. Preserve completeness and naturalness. Never truncate a sentence unnaturally just to hit target_words. Existing validity behavior is unchanged: below 160 words is hard-invalid, 160-300 words is the empirical preferred band, and above 300 words is an empirical warning rather than a hard rejection.
- Write original content. Do not quote, reproduce, lightly paraphrase, or imitate any official ETS or practice-test passage or question.
- Generate semantic content only. Do not emit `passage_id` or question `item_id`; trusted pipeline code attaches those deterministic identity fields after generation. Do not put the domain or title in those IDs.
- Produce exactly `question_count` questions in one response and one invocation. The model-facing schema provides `detail_questions`, `vocabulary_in_context_questions`, `inference_questions`, `main_idea_questions`, and `reference_questions` collections. Put exactly the requested number in each type-specific collection, including an empty array for a zero quota; together they must exactly match `question_count` and `question_type_counts`. Do not emit a flat `questions` array and do not attempt to reproduce an exact cross-type question order; trusted pipeline code deterministically interleaves the collections after generation.
- Give every question exactly four non-empty, distinct choices labeled A, B, C, and D.
- Make exactly one choice defensibly correct and make the item answerable from the passage.
- For INFERENCE questions, vary reasoning depth according to what the passage naturally supports. Explicit restatement should not dominate, and a simple one-step paraphrase or inversion should not be the default. Regularly require a conclusion that must be derived from the passage's implications, relationships, conditions, causes, comparisons, or consequences when naturally supported by the passage. Some items may require a small supported inference, while genuine supported inference should also occur regularly. When naturally supported, use information distributed across more than one sentence or idea. Multi-sentence or cross-idea reasoning is appropriate when naturally supported by the passage. Never force cross-sentence or cross-idea reasoning when the passage does not support it. Every keyed inference must remain fully supported by the passage and fully entailed by the text, with one unique defensible answer and no unsupported speculation. Do not create difficulty through simple negation/reversal or artificial logical tricks. Distractors should be plausible but not entailed.
- For VOCABULARY_IN_CONTEXT questions, both ordinary dictionary senses and
  context-clarified senses are acceptable. Do not require strong context
  dependence and do not choose obscure vocabulary merely to increase
  difficulty.
  The keyed synonym must match the target word's actual sense in its local
  sentence. When a target word is polysemous, distinguish between legitimate
  dictionary senses using grammatical construction, collocation, and local
  context. Distractors may use other legitimate dictionary senses when those
  senses are wrong in the sentence. The rationale must explain why the keyed
  sense fits the local usage.
- Keep correct options from being systematically the longest or most specific.
  Give distractors comparable grammatical form and approximate information
  density. Do not pad options merely to equalize character counts; preserve
  semantic quality when exact lengths differ naturally.
- For each question, provide the intended answer and private evidence metadata. The evidence paragraph is one-based and its anchor must be an exact phrase from that paragraph. The rationale is internal QA metadata.
- Use natural academic English and conventional TOEFL ITP-style wording. Do not include markdown, answer explanations outside the schema, or commentary.

Return only one JSON object matching the supplied v0.2.2 grouped semantic Generator output schema.
