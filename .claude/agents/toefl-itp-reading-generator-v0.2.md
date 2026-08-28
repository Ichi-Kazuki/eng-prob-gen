---
name: toefl-itp-reading-generator-v0.2
description: Original variable-length TOEFL ITP-style Reading Comprehension set generator
version: v0.2
tools: Read
---

# Reading Comprehension Generator v0.2

Generate one original academic expository passage and its complete question
set. The deterministic plan in the task input is authoritative: use the
domain, target word count, four-paragraph target, `question_count`, and the
exact ordered `question_plan`.

Requirements:

- Write approximately the planned word count, with exactly four non-empty paragraphs.
- Write original content. Do not quote, reproduce, lightly paraphrase, or imitate any official ETS or practice-test passage or question.
- Set `passage_id` exactly to `rc-` plus the plan seed as eight lowercase hexadecimal digits; set item IDs to that exact passage ID plus `-q1`, `-q2`, and so on. Do not put the domain or title in these IDs.
- Produce exactly `question_count` questions in one response and one invocation. The sequence of question types must exactly match `question_plan`; repeated types are allowed.
- Give every question exactly four non-empty, distinct choices labeled A, B, C, and D.
- Make exactly one choice defensibly correct and make the item answerable from the passage.
- For each question, provide the intended answer and private evidence metadata. The evidence paragraph is one-based and its anchor must be an exact phrase from that paragraph. The rationale is internal QA metadata.
- Use natural academic English and conventional TOEFL ITP-style wording. Do not include markdown, answer explanations outside the schema, or commentary.

Return only one JSON object matching the supplied v0.2 canonical output schema.
