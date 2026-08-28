---
name: toefl-itp-reading-generator-v0.2.1
description: Original variable-length TOEFL ITP-style Reading Comprehension set generator
version: v0.2.1
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
- Set `passage_id` exactly to `rc-` plus the plan seed as eight lowercase hexadecimal digits; set item IDs to that exact passage ID plus `-q1`, `-q2`, and so on. Do not put the domain or title in these IDs.
- Produce exactly `question_count` questions in one response and one invocation. The count of each question type must exactly match `question_type_counts`; repeated types are allowed. Do not follow an arbitrary exact question-type sequence.
- Give every question exactly four non-empty, distinct choices labeled A, B, C, and D.
- Make exactly one choice defensibly correct and make the item answerable from the passage.
- For each question, provide the intended answer and private evidence metadata. The evidence paragraph is one-based and its anchor must be an exact phrase from that paragraph. The rationale is internal QA metadata.
- Use natural academic English and conventional TOEFL ITP-style wording. Do not include markdown, answer explanations outside the schema, or commentary.

Return only one JSON object matching the supplied v0.2 canonical output schema.
