# Online Metrics & Feedback

> Offline evals tell you whether an agent can do the tasks you wrote. Production tells you whether it does the tasks users bring. Users rarely rate anything, and the ones who do are mostly unhappy. So measure what they *do* (escalate, rephrase, abandon) alongside latency, cost and tool errors. Compare a canary against the baseline with a test that knows how much data it has, and put people on reading the right conversations.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 11 · Why agent evals are hard; Phase 11 · Tracing with OpenTelemetry
**Time:** ~40 minutes

## Learning Objectives

- Choose production metrics for an agent: explicit feedback, implicit signals, reliability, latency percentiles and cost.
- Explain why thumbs-up/down data is sparse and biased, and what to use instead.
- Compare a canary version against the baseline with a two-proportion test plus a minimum effect size, and estimate how much traffic detection needs.
- Build a human review queue that covers both flagged and unrated conversations.

## The Problem

You ship v2 of your support agent to 10% of traffic. The dashboard looks calm: thumbs-down rate unchanged at 55%, tool errors flat. Five days later you promote it to 100%, and the support team's queue fills with escalations. v2 had been handing off twice as many conversations to humans the whole time. The signal was there, in a metric nobody alerted on, at a sample size too small to see.

## The Concept

| Metric | Type | Why it matters | Pitfall |
|--------|------|----------------|---------|
| Thumbs up/down | Explicit | Direct user judgement | Few users rate; unhappy users rate more |
| Escalation rate | Implicit | The agent gave up or the user demanded a human | Some escalations are correct |
| Rephrase rate | Implicit | "That didn't answer my question" | Needs similarity detection in real logs |
| Tool error rate | Reliability | Broken integrations | Errors the agent recovered from still count |
| p50 / p95 latency | Experience | Typical and worst-case wait | Averages hide the tail |
| Cost per conversation | Business | Runaway loops show up here first | Compare per successful conversation |

**Canary comparison:** route a share of traffic to the new version and compare it to the baseline over the same period. Alert only when the canary is worse by at least a meaningful amount **and** the difference is unlikely to be noise (a two-proportion z-test; p < 0.01 here). Both conditions matter. Effect size alone alarms on noise. Significance alone alarms on differences too small to care about once traffic is large.

## Build It

```bash
cd code
python3 main.py
```

The log is **simulated** (seeded): 4,000 conversations over 10 days, with v2 rolled out to 10% of traffic from day 6. v2 has a planted problem: about twice as many conversations go badly, and most of those escalate.

### Step 1: metrics per version

```text
metric (days 6-10)                v1          v2
conversations                  1,803         197
feedback_coverage               7.1%        5.6%
thumbs_down_of_rated           55.5%       54.5%
escalation_rate                 7.7%       11.2%
rephrase_rate                   3.3%        4.1%
tool_error_rate                 2.8%        2.6%
p50_latency_ms                 1,456       1,655
p95_latency_ms                 2,979       3,681
cost_per_conversation        $0.0119     $0.0115
```

Two things to see. First, **thumbs-down is useless here.** About 6–7% of users rated anything, and the raters are mostly unhappy ones (55% thumbs-down when only ~11% of conversations went badly). v2's 11 ratings can't distinguish anything. Second, **the behavioural signals moved**: escalation +3.5 points, rephrasing up, and p95 latency +700 ms.

### Step 2: when does the alarm fire?

```python
def canary_check(events, metric="escalated", min_effect=0.03, alpha=0.01):
    ...
    if r2 - r1 >= min_effect and p < alpha:
        return Alert(metric, r1, r2, p)
```

```text
when would the canary alarm have fired? (escalation, needs +3 points and p < 0.01)
  through day  6:  38 v2 conversations -> no alert
  through day  7:  77 v2 conversations -> no alert
  through day  8: 116 v2 conversations -> no alert
  through day  9: 155 v2 conversations -> no alert
  through day 10: 197 v2 conversations -> no alert
```

It never fires. v2 really is worse, but ~200 conversations can't separate 7.7% from 11.2% at p < 0.01. This is the same lesson as Lesson 1, in production: **a canary has a detection limit**, and a quiet canary isn't evidence of a good one.

### Step 3: size the canary for the regression you care about

```text
how big must the canary be? first day the alert fires, by canary share:
   10% canary ( 197 v2 conversations in 5 days): no alert within 5 days
   30% canary ( 578 v2 conversations in 5 days): alert on day 7
   50% canary ( 987 v2 conversations in 5 days): alert on day 7
```

At 30% the same problem is caught on the second day. Before a rollout, decide the smallest regression you must catch and how fast, then size the canary and its duration to match, or accept explicitly that you won't catch it.

### Step 4: who reads what

```text
human review queue: 20 conversations (15 from the canary, 5 unrated)
```

Every canary thumbs-down and escalation first, then a random slice of *unrated* conversations. Most bad conversations are never rated, so a queue built only from thumbs-down shows you a biased sample of your failures.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Practice | Why |
|----------|-----|
| Alert on behavioural metrics (escalation, rephrase, abandonment), not just ratings | They cover every conversation |
| Size canaries from the effect you must detect | Small canaries can only see large regressions |
| Use percentiles for latency | p95 is what unhappy users experience |
| Track cost per conversation per version | Loops and verbose prompts show up as cost first |
| Feed reviewed failures back into the golden dataset (Lesson 2) | Online failures become offline tests |
| Tag traces with version, so every metric splits by version | Comparisons need clean cohorts |

Observability platforms (Langfuse, LangSmith, Arize Phoenix, Braintrust, Datadog LLM Observability, Helicone) compute many of these from traces (Lesson 6), collect user feedback through their SDKs, and support online evaluators on sampled production traffic.

## Ship It

`outputs/skill-online-agent-metrics.md` is a skill for setting up production monitoring of an agent: choose metrics per category, define alert rules with effect size and significance, size the canary, and design the human review queue.

## Exercises

1. **Easy.** Add an alert on p95 latency (more than 20% higher than baseline). Does it fire for the 10% canary?
2. **Medium.** Compute the minimum detectable escalation difference for a 10% canary over 5 days at p < 0.01 with 80% power, using the normal approximation. Check it by simulation.
3. **Medium.** Add a "cost per *resolved* conversation" metric (not escalated, not rephrased). Which version is cheaper by that measure?
4. **Hard.** Implement sequential testing: check the canary every day, but correct for repeated looks (for example with a stricter alpha per look). How much later does it alert, and how many false alarms does it avoid on a simulation where v2 is *not* worse?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Explicit feedback | "Ratings" | Thumbs, stars or comments users give on purpose |
| Implicit feedback | "Behavioural signals" | What users do: escalate, rephrase, abandon, copy the answer |
| Canary | "Gradual rollout" | Sending a share of real traffic to a new version and comparing |
| Effect size | "How much worse" | The size of the difference, separate from whether it's significant |
| Statistical power | "Can we even see it?" | The chance a test detects a real difference of a given size |
| Selection bias | "Who rates" | Feedback comes from an unrepresentative subset of users |

## Further Reading

- [Kohavi, Tang & Xu, Trustworthy Online Controlled Experiments (2020)](https://experimentguide.com/)
- [Google SRE book, Monitoring distributed systems (the four golden signals)](https://sre.google/sre-book/monitoring-distributed-systems/)
- [Google SRE workbook, Canarying releases](https://sre.google/workbook/canarying-releases/)
- [Langfuse: scores and user feedback](https://langfuse.com/docs/scores/overview)
- [Hamel Husain, A field guide to rapidly improving AI products (2025)](https://hamel.dev/blog/posts/field-guide/)
