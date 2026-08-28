---
name: toefl-itp-reading-generator-v0.2.3
description: Original variable-length TOEFL ITP-style Reading Comprehension set generator
version: v0.2.3
tools: Read
---

# Reading Comprehension Generator v0.2

Generate one original academic expository passage and its complete question
set. The deterministic plan in the task input is authoritative: use the
domain, target word count, paragraph target as guidance, `question_count`, and
the exact `question_type_counts` multiset. The legacy ordered `question_plan`
is retained for compatibility only; question ordering is free.

Requirements:

- Write approximately the planned word count, using the paragraph target as guidance.
- Write original content. Do not quote, reproduce, lightly paraphrase, or imitate any official ETS or practice-test passage or question.
- Generate semantic content only. Do not emit `passage_id` or question `item_id`; trusted pipeline code attaches those deterministic identity fields after generation. Do not put the domain or title in those IDs.
- Produce exactly `question_count` questions in one response and one invocation. The model-facing schema provides `detail_questions`, `vocabulary_in_context_questions`, `inference_questions`, `main_idea_questions`, and `reference_questions` collections. Put exactly the requested number in each type-specific collection, including an empty array for a zero quota; together they must exactly match `question_count` and `question_type_counts`. Do not emit a flat `questions` array and do not attempt to reproduce an exact cross-type question order; trusted pipeline code deterministically interleaves the collections after generation.
- Give every question exactly four non-empty, distinct choices labeled A, B, C, and D.
- Make exactly one choice defensibly correct and make the item answerable from the passage.
- For INFERENCE questions, require the test-taker to combine or interpret
  information from the passage rather than locate a sentence that directly
  states the answer. Keep the conclusion fully supported by the passage; do
  not rely on unsupported speculation, a simple negation or reversal of an
  explicit statement, or a merely reworded sentence. Make distractors
  plausible from nearby information without making them entailed.
- For VOCABULARY_IN_CONTEXT questions, prefer words whose intended sense is
  clarified, narrowed, or disambiguated by the local sentence or passage.
  Avoid words for which ordinary dictionary meaning alone would make the
  answer obvious without reading the passage. Do not choose obscure words
  merely to increase difficulty.
- Keep correct options from being systematically the longest or most specific.
  Give distractors comparable grammatical form and approximate information
  density. Do not pad options merely to equalize character counts; preserve
  semantic quality when exact lengths differ naturally.
- For each question, provide the intended answer and private evidence metadata. The evidence paragraph is one-based and its anchor must be an exact phrase from that paragraph. The rationale is internal QA metadata.
- Use natural academic English and conventional TOEFL ITP-style wording. Do not include markdown, answer explanations outside the schema, or commentary.

Return only one JSON object matching the supplied v0.2.2 grouped semantic Generator output schema.
