# The LLM judge says 92%. Do you believe it?

> Your team grades agent answers with an LLM-as-judge prompt: "Rate the answer's helpfulness and correctness from 1 to 10; 7+ is a pass." It reports a 92% pass rate. Before this number goes into a launch review, what do you check?

**Level:** 3
**Type:** Trade-off
**Time:** ~10 minutes
**Taught in:** 11-evaluation-and-observability/04-llm-as-judge-carefully, 11-evaluation-and-observability/02-golden-tasks-datasets

## Short answer

Treat the judge as a model that needs its own evaluation. Have humans label a sample (100–200) and measure agreement with the judge, especially on failures: how many bad answers does it pass? Check known biases: position, verbosity, self-preference, and leniency toward confident text. Make the rubric specific and binary per criterion ("states the correct refund amount: yes/no") with the reference or tool results available to the judge. Prefer code checks where possible. Report the judge's agreement rate next to the 92%.

## Full answer

### Validate the judge

- **Human-labelled calibration set** covering passes, failures and borderline cases.
- **Agreement metrics:** accuracy, and especially false-pass rate (bad answers judged good).
- **Stability:** run the judge twice; does it agree with itself?
- **Drift:** re-check when the judge model or prompt changes.

### Known biases

| Bias | Mitigation |
|------|------------|
| Verbosity (longer looks better) | Rubric about specific facts; penalise unsupported claims |
| Position (in pairwise comparisons) | Swap order and average |
| Self-preference | Judge with a different model family when possible |
| Leniency on fluent text | Give the judge the ground truth and ask about it specifically |

### Better rubrics

- Several binary criteria, each answerable from evidence: "Is the amount equal to the tool result's amount?", "Does it promise anything not in policy?"
- Ask for the evidence (a quote) before the verdict.
- Include tool results and reference data in the judge's input.

### Use code where you can

Amounts, ids, citations, schema validity and side effects are cheaper and exact in code. Use the judge for tone, helpfulness and coverage.

## Follow-ups

- **L3.** The judge agrees with humans 90% of the time. Is that good? *Expected:* Depends on where it disagrees; if most disagreements are false passes on harmful answers, it's not fit for gating.
- **L3.** How do you use a judge for regression testing? *Expected:* Pairwise comparison of old vs new outputs on the same inputs, with order swapping, often more sensitive than absolute scores.
- **L4.** How do you stop teams from tuning prompts to the judge? *Expected:* Keep a human-audited holdout and periodic human review; rotate or ensemble judges for important gates.

## Wrong answers

- "92% from a strong model is reliable." Unvalidated judges have unknown false-pass rates.
- "Use a 1–10 scale for nuance." Fine-grained scales are less consistent; binary criteria are easier to validate.
- "Use the same model as the agent so it understands the task." Self-preference bias inflates scores.
