# The golden set is all green, and users are unhappy

> Your agent passes 96% of your 200-task golden set, every release. Meanwhile support tickets about the agent are rising and user ratings dropped. What's going on, and what do you change?

**Level:** 3
**Type:** Debug
**Time:** ~10 minutes
**Taught in:** 11-evaluation-and-observability/02-golden-tasks-datasets, 11-evaluation-and-observability/08-online-metrics-feedback, 11-evaluation-and-observability/07-replay-and-regression

## Short answer

The eval set no longer represents what users do. Likely causes: it was written by the team at launch and drifted from real traffic; it's saturated (easy tasks you always pass); it checks answers, not the things users complain about (latency, tone, wrong actions, refusing valid requests); or the graders are lenient. Fix it from production: sample real conversations, cluster the complaints, turn each failure cluster into eval tasks with strict checks, weight the set by real traffic mix, and track online metrics (resolution, escalation, corrections, thumbs-down reasons) next to offline scores.

## Full answer

### Find the gap

| Check | Question |
|-------|----------|
| Traffic mix | Do eval task types match production proportions? |
| Difficulty | How many tasks have passed every release for months? |
| What's graded | Are complaints about things you don't measure (speed, tone, refusals)? |
| Grader quality | Spot-check passes: would a human agree? |
| Version drift | Do tasks reflect current tools, policies and products? |

### Rebuild with production in the loop

1. Sample failing conversations weekly (thumbs-down, escalations, repeated questions).
2. Label the failure category; cluster.
3. Write each cluster's representative cases as golden tasks with outcome and trajectory checks.
4. Keep a "hard" slice and report it separately; saturation hides there.
5. Re-weight the headline score by traffic mix.

### Online metrics

Task resolution without escalation, user corrections ("no, I meant…"), retries, abandonment, latency percentiles, cost per resolved task. Offline evals gate releases; online metrics tell you if the gate measures the right thing.

## Follow-ups

- **L3.** How do you avoid overfitting to the new cases? *Expected:* Hold out a portion, refresh from new traffic regularly, and check that fixes generalise to unseen examples of the same cluster.
- **L3.** How do you use thumbs-down data when it's sparse and noisy? *Expected:* As a pointer for sampling, not a metric alone; read the conversations and categorise.
- **L4.** What would you put on the release dashboard? *Expected:* Offline pass rate by slice with intervals, regressions vs last release, online resolution and escalation trends, cost and latency.

## Wrong answers

- "96% is great; the complaints are edge cases." Rising tickets mean the eval isn't measuring what users experience.
- "Add more tasks of the same kind." More of what you already pass doesn't find the problem.
- "Switch to a better LLM judge." The issue is coverage and representativeness before grader quality.
