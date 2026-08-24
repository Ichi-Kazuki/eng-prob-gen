# TOEFL ITP Written Expression Generator v2.0

このディレクトリは、既存の `agents/toefl_itp_grammar_generator/` と完全に分離されたWE専用v2実装である。

- schema: `schema/written_expression_item_v2.schema.json`
- format config: `config/we_v2_format_config.json`
- deterministic validator: `scripts/validate_format.py`
- contract validator: `scripts/validate_output.py`

v2の構築順序は clean sentence → clean validation → one-error mutation → uniqueness audit → four local spans → deterministic format diagnostics で固定する。既存v1.1のfull-sentence partition outputを入力テンプレートとして再利用しない。
