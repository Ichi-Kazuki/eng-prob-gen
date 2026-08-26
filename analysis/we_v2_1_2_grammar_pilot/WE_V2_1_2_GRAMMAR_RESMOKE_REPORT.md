# WE v2.1.2 Grammar Mutation Safety — Fresh 25-item Re-smoke

Date: 2026-08-26  
Generator lock: **WE Generator v2.1.2**  
Format logic: **v2.1.1 locked**  
75-item Validation: **NOT RUN**

## Deterministic results

- Fresh items: **25**
- Historical exact sentence matches: **0**
- Mutation safety: **25/25**
- Metadata consistency: **25/25**
- External mutation: **0**
- Existing v2.1.1 format validator: **25/25**
- Existing format-band diagnostics: **{'PREFERRED': 6, 'WARNING': 6, 'EXTREME': 13}** (diagnostic only)

## Runtime boundary

The live Generator, independent Reviewer, and Solver runtimes are unavailable
in this workspace. This artifact is a fresh offline safety-smoke cohort so the
new guards and the locked format gates can be exercised without inventing
Reviewer/Solver judgments. Grammar quality is therefore **NOT_EVALUATED**;
the sealed key is not to be used as an independent blind verdict.

Blind artifact: `analysis/we_v2_1_2_grammar_pilot/we_v2_1_2_grammar_pilot_blind.json`  
Sealed key: `analysis/we_v2_1_2_grammar_pilot/we_v2_1_2_grammar_pilot_sealed_key.json`

Template audit: `analysis/we_v2_1_2_grammar_pilot/mutation_template_audit.json`

Output hashes:

- Blind: `sha256:ba568e5f29cb233b70dc58de6ccfbc07c42aa9fbc21dab4543481f97cc880782`
- Sealed key: `sha256:6dc9940ffbfd7167ca83f5e8ef2a7bf1a53249a6408383ad2f344e881cdf3a67`
