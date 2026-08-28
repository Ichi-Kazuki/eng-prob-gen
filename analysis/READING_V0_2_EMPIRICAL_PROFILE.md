# Reading v0.2 lightweight empirical profile

This profile uses derived measurements from the four available official Section
3 RC reference PDFs under `source/`: B, C, D, and E. It covers 20 passages and
200 questions. The source wording is not retained or used in prompts.

The observed passage question counts were 7–14, with a mean of 10. The
approximate OCR-based passage word counts were 160–300 words. In this small
sample, the relationship between passage word count and question count was
weak, so the deterministic v0.2 planner samples those dimensions independently
within the observed ranges rather than forcing a linear relationship.

The planner bootstraps an observed per-passage question-type composition and
adapts it only when the requested question total differs from that row. This
preserves realistic within-passage mixes while retaining the profile's
aggregate proportions over many seeds. The observed rows contain at most one
main-idea item, so the adapter enforces that structural upper bound. It does
not impose a one-of-each rule.

One committed measurement row has an abstract type-count residual of one
question relative to its declared total. The planner preserves that observed
row and reconciles the residual through the same deterministic adapter used
when totals differ, while taking aggregate type weights from the profile's
published totals.

The abstract primary profile was detail-heavy (74/200), followed by
vocabulary-in-context (63/200), inference (27/200), reference (21/200), and
main-idea (15/200). These remain the planning categories. A secondary item
subtype can distinguish direct or paraphrased detail, negative/EXCEPT detail,
local or cross-idea inference, rhetorical purpose, contextual vocabulary, main
idea, and antecedent reference. The source profile does not reliably measure
subtype frequencies, so subtypes are not assigned empirical weights.

Generated items may also carry private distractor metadata describing the
intended error mechanism of each incorrect option. It is validated in the
Generator contract and excluded from blind Reviewer and Solver inputs.

The older `reading/calibration.json` is retained only for legacy v0.1
reference and is explicitly deprecated; this file is authoritative for v0.2
passage-length and composition planning. This profile provides structural and
qualitative guidance only, not psychometric equivalence to official TOEFL ITP
questions.

This release remains passage-level. A 50-question Level 1 section assembler is
deferred as follow-up work; when added, it should choose whole passage plans
whose question counts sum exactly to 50 rather than truncating a passage.
