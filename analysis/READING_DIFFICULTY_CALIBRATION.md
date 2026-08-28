# Reading difficulty calibration v0.1

This layer adds a deterministic structural-difficulty interface to Reading v0.2
without claiming TOEFL ITP score equivalence.

The Planner emits a `difficulty_profile` with six dimensions: lexical load,
syntactic load, paraphrase distance, evidence distance, inference depth, and
distractor competitiveness. The Generator treats those dimensions as
construction constraints. Diagnostics then estimate observable proxies from
the generated passage and private QA metadata.

The current thresholds are engineering guardrails only. They are intended to
catch artificial hardness (obscure lexical load, excessive sentence length)
and artificial easiness (surface-copy answers, distractors dominated by
direct contradiction). They are deliberately not used as a hard acceptance
gate.

Next calibration step: measure the same features on the official-derived B-E
reference set, preferably with a held-out-test design. Once learner response
data exists, add empirical item difficulty, discrimination, and eventually a
Rasch/IRT layer without changing the Planner/diagnostics interface.
