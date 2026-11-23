# Why Agent Evals Are Hard

> An agent eval is a measurement of a random process. Run the same agent on the same 50 tasks five times and you get five different scores. A truly better agent can score lower in a single run. "Did it pass?" has more than one honest answer. Before building any eval harness, learn to see the noise, size your eval to beat it, and say which question your metric answers.

**Type:** Learn
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 10 · Build a mini coding agent; Phase 1 · Sampling: temperature, top-p, determinism
**Time:** ~35 minutes

## Learning Objectives

- Show, with simulated agents whose true success rate is known, how much one eval run varies.
- Compute a 95% confidence interval for a success rate, and decide how many trials a task needs.
- Distinguish pass@k (succeeds at least once in k tries) from pass^k (succeeds every time in k tries).
- Compare two agents with a paired bootstrap over tasks, and explain why final-answer and trajectory grading disagree.

## The Problem

You change a prompt, run your 50-task eval once, and the score goes from 66% to 62%. You revert the change. A week later someone else makes the same change, runs once, gets 70%, and ships it. Both decisions were coin flips. Agents sample from a model, call tools with variable results, and take different paths each run. One run per task measures your luck as much as your agent.

Then there's what "pass" means. The agent got the right total but looked up the prices in a different order than the reference: pass or fail? It got the right answer by guessing instead of using tools: pass or fail? Different metrics answer different questions, and picking one without knowing which question you're asking is how teams end up optimising the wrong thing.

## The Concept

| Problem | Why it happens | What to do |
|---------|----------------|------------|
| Scores vary run to run | Sampling, tool variability, path dependence | Multiple trials per task; report intervals, not points |
| Small differences look real | 50 tasks is a small sample | Paired comparison over the same tasks, with an interval on the difference |
| "Works sometimes" ≠ "works" | One success hides unreliability | Report pass^k alongside pass@1 |
| Many correct paths | Agents can reach the goal in different orders | Grade outcomes (final state/answer) plus *constraints* on the path, not exact paths |
| Correct answer, wrong process | Guessing, skipping required steps | Check required tool calls and forbidden actions (Lesson 3) |

**Three numbers per task, from n trials with c successes:**

| Metric | Formula | Question it answers |
|--------|---------|---------------------|
| pass@1 | c / n | How often does one attempt work? |
| pass@k | 1 − C(n−c, k) / C(n, k) | If I can try k times and pick a winner, how often do I succeed? |
| pass^k | C(c, k) / C(n, k) | If a user tries k times, how often does it work *every* time? |

pass@k suits workflows where you can verify and retry, like code with tests. pass^k suits customer-facing agents, where every conversation has to work.

## Build It

```bash
cd code
python3 main.py
```

The agents are **simulated**: each task has a fixed success probability per agent. In a real eval you never know the true rate. Here we do, so you can see how far the measurements land from it.

```text
true success rates (known only because the agents are simulated): A 64.4%, B 67.5%
```

### Step 1: the same eval, five times

```text
1. One run per task, repeated five times (same agent, same tasks):
   A scored 70%, 64%, 70%, 62%, 62%   (spread 62%–70%)
```

Nothing changed between those runs. An 8-point swing is pure noise.

### Step 2: confidence intervals

```python
def wilson(successes, n, z=1.96):
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
```

```text
2. More trials shrink the uncertainty:
    1 trial(s) x 50 tasks: 66.0%  95% interval 52.2%–77.6%  (width 25.4%)
    3 trial(s) x 50 tasks: 62.7%  95% interval 54.7%–70.0%  (width 15.3%)
   10 trial(s) x 50 tasks: 62.2%  95% interval 57.9%–66.3%  (width 8.5%)
```

The Wilson interval behaves well near 0% and 100%, where the textbook `p ± 1.96·√(p(1−p)/n)` gives nonsense like negative rates. One caveat: it treats all attempts as independent, but attempts on the same task are correlated (a hard task is hard every time), so the true interval is somewhat wider. Step 4's bootstrap over tasks accounts for that.

### Step 3: pass@k vs pass^k

```text
3. pass@k vs pass^k on one task with a 70% success rate (10 trials, 7 successes):
   k=1: pass@1 = 0.70   pass^1 = 0.70
   k=3: pass@3 = 0.99   pass^3 = 0.29
   k=5: pass@5 = 1.00   pass^5 = 0.08
```

The same agent is "99% successful" (pass@3) and "29% reliable" (pass^3). Both are true. Report the one that matches how the agent will be used.

### Step 4: is B better than A?

```python
def paired_bootstrap(a, b, rng, iters=4000):
    diffs = [b[i] - a[i] for i in range(n)]
    boots = sorted(mean(diffs[rng.randrange(n)] for _ in range(n)) for _ in range(iters))
```

Pair by task (both agents saw the same tasks), resample tasks with replacement, and read the 2.5th and 97.5th percentiles of the mean difference:

```text
4. Is B better than A? 50 tasks, 1 trial each, then 5 trials each:
   1 trial(s): A 66.0%, B 62.0%, difference -4.0% (95% CI -20.0% to +12.0%) -> can't tell
   5 trial(s): A 60.0%, B 68.8%, difference +8.8% (95% CI +1.2% to +16.4%) -> B is better
```

With one trial, the truly better agent scored 4 points *lower*, and the interval said, correctly, "can't tell". With five trials, the interval excludes zero. Notice the measured +8.8% still overshoots the true +3.1%: an interval that excludes zero tells you the direction, not the exact size.

### Step 5: what counts as a pass

```text
5. Grading 3 runs (2 correct, 1 wrong): exact-trajectory match passes 1, final-answer check passes 2
```

Run 2 looked up the pen price before the notebook price. It's correct, and an exact-trajectory grader fails it. Lesson 3 builds graders that check what matters about the path (required calls, forbidden calls, order only where order matters) instead of the exact sequence.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Rule of thumb | Why |
|---------------|-----|
| ≥ 3 trials per task for anything you'll decide on; 5–10 for small task sets | Single runs are noise-dominated |
| Report score ± interval, and n tasks × k trials | A point estimate invites over-reading |
| Compare agents paired, on the same tasks and trials | Removes task-difficulty variance from the comparison |
| Report pass^k for user-facing agents | Users experience every failure, not the best of k |
| Fix seeds and temperatures where you can, but don't rely on them | Providers don't guarantee determinism; tools vary anyway |
| Grade outcomes, constrain process | Many correct paths exist; a few wrong ones matter |

## Ship It

`outputs/skill-eval-design-questions.md` is a skill that interviews you before you build an eval: what decision it informs, which metric answers that question (pass@1, pass@k, pass^k), how many tasks and trials you need for the difference you care about, and how passes will be graded.

## Exercises

1. **Easy.** Change `make_agents` so B is truly 10 points better. How many trials do you need before the 1-trial comparison reliably says "B is better"?
2. **Medium.** Implement a sample-size helper: given a baseline rate and the smallest difference you care about, estimate the number of tasks × trials needed for the bootstrap interval to exclude zero 80% of the time. Check it by simulation.
3. **Medium.** Add a third grading mode to step 5: "required calls" (both `price` lookups must appear, in any order). How does it grade the three runs?
4. **Hard.** Replace the simulation with real runs: use Phase 10's mini agent on `sample_repo` with a local model, 5 trials. Report pass@1 with a Wilson interval and pass^5.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Trial | "A run" | One attempt by the agent at one task |
| Confidence interval | "Error bars" | A range likely to contain the true rate, given the sample |
| pass@k | "Best of k" | Probability that at least one of k attempts succeeds |
| pass^k | "Reliability" | Probability that all k attempts succeed |
| Paired comparison | "A/B on the same tasks" | Comparing two agents task by task, which removes task-difficulty noise |
| Bootstrap | "Resampling" | Estimating uncertainty by recomputing a statistic on resampled data |

## Further Reading

- [Chen et al., Evaluating large language models trained on code (2021)](https://arxiv.org/abs/2107.03374), the unbiased pass@k estimator
- [Yao et al., τ-bench: a benchmark for tool-agent-user interaction (2024)](https://arxiv.org/abs/2406.12045), pass^k
- [Miller, Adding error bars to evals: a statistical approach to language model evaluations (2024)](https://arxiv.org/abs/2411.00640)
- [Kapoor et al., AI Agents That Matter (2024)](https://arxiv.org/abs/2407.01502)
- [Wilson, Probable inference, the law of succession, and statistical inference (1927)](https://www.jstor.org/stable/2276774)
