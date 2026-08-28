# Reading v0.2 lightweight empirical profile

This profile uses derived measurements from the four available official Section
3 RC reference PDFs under `source/`: B, C, D, and E. It covers 20 passages and
200 questions. The source wording is not retained or used in prompts.

The observed passage question counts were 7–14, with a mean of 10. The
approximate OCR-based passage word counts were 160–300 words. In this small
sample, the relationship between passage word count and question count was
weak, so the deterministic v0.2 planner samples those dimensions independently
within the observed ranges rather than forcing a linear relationship.

The abstract question profile was detail-heavy (74/200), followed by
vocabulary-in-context (63/200), inference (27/200), reference (21/200), and
main-idea (15/200). The planner uses these as weights; repeated types are
expected and no one-of-each-type rule is applied.
