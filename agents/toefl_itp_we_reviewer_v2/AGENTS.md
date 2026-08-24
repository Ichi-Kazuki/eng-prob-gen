# TOEFL ITP Written Expression Reviewer v2.0

このディレクトリは、既存の `agents/toefl_itp_grammar_reviewer/` と完全に分離されたWE専用v2実装である。

- schema: `schema/reviewer_output_v2.schema.json`
- contract validator: `scripts/validate_output.py`

Review orderは blind grammar audit → one-error-only → answer uniqueness → deterministic format audit → target/metadata → final verdict。`grammar_validity`と`format_validity`を混ぜない。
