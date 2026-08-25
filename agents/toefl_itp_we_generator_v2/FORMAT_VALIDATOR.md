# WE v2.1.1 deterministic format validator

The lexical token contract is shared with the planner, format analysis, and
pilot integrity audit through `shared/tokenization.py`: Unicode letters and
numbers form tokens, internal ASCII/curly apostrophes and hyphens stay inside
one token, and punctuation-only fragments are excluded. The
`same_phrase_multiple_distractors` setting is a soft preference because no
deterministic phrase-group parser is defined.

`scripts/validate_format.py` is independent of the LLM Generator and Reviewer. It applies the addendum tokenization rule and calculates span alignment, overlap/order, word counts, marked coverage, unmarked context, three gaps, correct-span size/type, empirical percentile profile, and format band.

## Bands

`config/we_v2_format_config.json` records the method as `nearest_rank_empirical_quantile`:

- PREFERRED: q10 through q90, inclusive
- WARNING: outside PREFERRED but within q05 through q95
- EXTREME: below q05 or above q95

The thresholds are computed from the official 125 item-level records in `analysis/we_format/written_expression_format_official.json`. They are diagnostic bands, not a small-batch quota and not a universal grammar rejection threshold.

## Distance

`format_distribution_distance` is the root-mean-square of standardized distances for sentence word count, coverage ratio, unmarked word count, mean span length, and max span length. The max-span term is omitted because the official item-level standard deviation is zero; max span remains in the percentile profile and band diagnostics.

The validator never counts grammar errors. A grammar-validity decision belongs to the blind Reviewer phase.
