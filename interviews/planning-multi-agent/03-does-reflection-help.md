# Does asking the model to reflect actually help?

> A teammate added a "reflect on your answer and improve it" step after every agent response. Quality looked better in a demo. Costs doubled. How would you decide whether reflection is worth it, and when does it help?

**Level:** 3
**Type:** Concept
**Time:** ~10 minutes
**Taught in:** 06-planning-and-reasoning/05-reflection-self-critique, 06-planning-and-reasoning/06-reflexion-learning-from-failures, 06-planning-and-reasoning/07-verifiers-and-checkers

## Short answer

Self-critique helps most when the critique is grounded in new information, such as test output, a failed tool call or a checker's result. Without that, the model often rubber-stamps its own answer, or "fixes" correct answers into wrong ones, because it's judging with the same knowledge that produced the mistake. So measure it: run the eval set with and without reflection, report wins, losses and cost, and keep reflection only where it's triggered by a failure signal or a specific checklist.

## Full answer

### When it works and when it doesn't

| Works better | Works worse |
|--------------|-------------|
| Feedback is external: tests, errors, validators | Feedback is the model's own opinion |
| Specific checklist ("does every claim have a source?") | Vague ("improve your answer") |
| Reasoning and code tasks with checkable outcomes | Factual questions the model doesn't know |
| Triggered when something failed | Run on every response |

### Reflexion-style memory

After a failed attempt, write a short lesson ("the API needs dates in UTC") and include it in the next attempt. It helps across retries of the same task when failures are informative.

### How to evaluate

- Same eval set, with and without the step, several runs each.
- Count **flips:** wrong→right (gains) and right→wrong (harms). Demos only show gains.
- Cost and latency per successful task.
- Slice by task type; reflection may help code and hurt chit-chat.

### Cheaper alternatives

A verifier that triggers reflection only on failure; a checklist-based critique on high-stakes outputs only; better tools so the first answer is right.

## Follow-ups

- **L3.** The reflection step improves accuracy by 3 points and doubles cost. Ship it? *Expected:* Look at which tasks gain and whether the gains are worth it there; make it conditional (high stakes or failure-triggered) instead of global.
- **L3.** Why can reflection make answers worse? *Expected:* Sycophancy toward perceived criticism, overcorrection, and the same blind spots; without new evidence, a "critique" can change correct parts.
- **L4.** How does this relate to reasoning models? *Expected:* They already do internal deliberation; external reflection adds less, while external verification still adds a lot.

## Wrong answers

- "Reflection always improves quality; it's like a second draft." Without new information, gains are inconsistent and regressions are common.
- "It looked better in the demo." Demos sample gains; you need flips counted on an eval set.
- "Use a bigger model for the reflection step." A stronger critic helps, but grounding the critique in checks matters more.
