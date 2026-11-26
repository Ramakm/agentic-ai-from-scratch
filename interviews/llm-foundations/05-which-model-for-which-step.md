# One model for everything, or a different model per step?

> Your agent uses the largest frontier model for every call. It's accurate but slow and expensive. A teammate proposes a small model for most steps and the big one "when needed". How would you decide which steps get which model, and how would you know it worked?

**Level:** 3
**Type:** Trade-off
**Time:** ~10 minutes
**Taught in:** 01-llm-foundations/09-model-selection-for-agent-work, 01-llm-foundations/10-why-capable-models-still-fail, 11-evaluation-and-observability/02-golden-tasks-datasets

## Short answer

Decide per step with data. Split the agent's calls by job (routing, tool selection, extraction, planning, final writing), build a small eval set for each, and run candidate models on it with cost and latency. Cheap models are often fine for classification, extraction and formatting; planning, recovering from errors and long multi-step tool use are where large models usually earn their price. Then route statically by step type before trying dynamic routing, and keep an end-to-end eval to catch interactions. A step that fails 3% more often can cost more in retries and escalations than it saves.

## Full answer

### Break the agent into jobs

| Job | Typical difficulty | Often OK with a small model? |
|-----|--------------------|------------------------------|
| Intent routing, classification | Low | Usually |
| Extraction into a schema | Low–medium | Often, with validation |
| Choosing a tool and arguments | Medium | Depends on tool count and ambiguity |
| Planning multi-step work | High | Rarely |
| Recovering after an error or surprise | High | Rarely |
| Final answer writing | Medium | Often |

### Measure per job

For each job, 30–100 labelled cases from real traffic. Run each candidate several times. Record success rate, cost per call and latency (p50 and p95). Plot cost vs success; pick the cheapest model on the acceptable frontier.

### Count the hidden costs

- **Retries:** a model that fails validation 5% of the time adds calls.
- **Downstream damage:** a wrong tool choice early wastes every later step.
- **Escalation:** a fallback to the big model after failure costs both calls.
- **Operational:** two providers or models means two sets of limits, outages and prompt variants.

### Routing styles

| Style | How | Risk |
|-------|-----|------|
| Static by step | Each node uses a fixed model | Simple; may overpay on easy instances |
| Cascade | Try small, escalate on low confidence or validation failure | Confidence signals are unreliable; double cost on hard cases |
| Learned router | Classifier predicts difficulty | Needs data; another component to maintain |

Start static. Move to cascades only where a verifier gives a reliable failure signal (schema validation, tests passing).

## Follow-ups

- **L3.** The small model scores 2 points lower on your end-to-end eval but costs a fifth. Ship it? *Expected:* Depends on what the 2 points are. Read the failures: if they're harmless formatting issues, maybe; if they're wrong refunds, no. Weight failures by impact, not count.
- **L3.** How do you keep this decision current? *Expected:* Re-run the per-step evals when models or prompts change; track production success and cost per step; treat model choice as config with a regression suite.
- **L4.** How would you present this to leadership? *Expected:* Cost per successful task, not cost per token, with quality and latency side by side and the main risks.

## Wrong answers

- "Use the best model everywhere; quality is all that matters." Latency and cost are product requirements, and many steps don't need it.
- "Use the cheapest model and fix problems with prompting." Some failures (planning, recovery) don't prompt away.
- "Pick based on public leaderboards." Benchmarks rarely match your tools, data and failure costs; measure on your tasks.
