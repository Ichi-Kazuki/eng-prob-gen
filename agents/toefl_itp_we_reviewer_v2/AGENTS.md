# TOEFL ITP Written Expression Reviewer v2.0

このディレクトリは、既存の `agents/toefl_itp_grammar_reviewer/` と完全に分離されたWE専用v2実装である。

- schema: `schema/reviewer_output_v2.schema.json`
- contract validator: `scripts/validate_output.py`

Review orderは blind grammar audit → one-error-only → answer uniqueness → deterministic format audit → target/metadata → final verdict。`grammar_validity`と`format_validity`を混ぜない。

## Blind responsibility boundary

During a blinded invocation the Generator target and metadata are withheld.
The Reviewer must still perform its blind grammar, one-error-only, answer
uniqueness, format, and naturalness judgments, but it must not emit or certify
`checks.target_metadata`. The Orchestrator performs that Generator metadata
consistency check deterministically after the blind response and before the
formal Reviewer record is accepted. A contradictory blind or formal record
fails closed.
