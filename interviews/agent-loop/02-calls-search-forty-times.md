# The agent called search forty times with the same query

> In production traces you find runs where the agent calls `search("refund policy EU")` over and over, each time getting the same results, until it hits the 50-step limit. Each of those runs costs about $2. What's happening and how do you fix it?

**Level:** 2
**Type:** Debug
**Time:** ~8 minutes
**Taught in:** 03-the-agent-loop/12-debugging-a-stuck-loop, 03-the-agent-loop/03-stop-conditions-max-steps, 03-the-agent-loop/11-cost-and-step-budgets

## Short answer

The agent is stuck: it doesn't find what it needs, and nothing in the observation tells it to change course, so it repeats the most plausible action. Read a few traces to find the cause (results don't contain the answer, the tool returned an error the model misreads, or the goal is unreachable). Then add a guard: detect identical calls (same tool and arguments) repeated N times and inject an observation telling the model to try something different or stop, with a hard stop after that. Lower the step limit to what successful runs actually use, and add a cost budget.

## Full answer

### Diagnose before fixing

| Look at | Common finding |
|---------|----------------|
| The repeated tool result | Empty or irrelevant results; the model hopes for different ones |
| The model's reasoning or text between calls | It doesn't notice it already searched |
| The task | Impossible with the given tools; nothing tells the model to give up |
| Context size at that point | Early turns truncated, so it lost track of previous searches |

### Guards

1. **Repeat detection.** Hash `(tool, canonical args)`. On the second repeat, return: "You already ran this search twice with the same results. Try different terms, another source, or answer with what you have." On the third, stop.
2. **Progress check.** No new information in K steps ends the run with a partial answer.
3. **Budgets.** Step limit from the distribution of successful runs (p99 plus margin), plus token and cost ceilings.
4. **Graceful stop.** When stopping, ask the model once for its best answer with what it has, flagged as incomplete.

### Fix the cause, too

Better search (query rewriting, other sources), a tool that says "no results for X; similar: Y", and a prompt that permits "I couldn't find this".

## Follow-ups

- **L2.** Is identical-call detection enough? *Expected:* No: near-duplicates (same query with a word changed) loop too. Normalise arguments or compare results; also track lack of progress.
- **L3.** How do you choose the step limit? *Expected:* Look at step counts of successful runs; set the limit just above the tail; alert when runs hit it, because each hit is either a bug or an impossible task.
- **L3.** How would you catch this before users do? *Expected:* Dashboards on steps per run and runs hitting limits; eval tasks designed to be unanswerable, checking that the agent stops early and says so.

## Wrong answers

- "Raise max_steps so it has time to finish." It's not short of time; it's stuck. You just pay more.
- "Lower temperature." Repetition is the deterministic behaviour; lower temperature can make it worse.
- "Tell it in the prompt not to repeat searches." Helps somewhat, but a code guard is what stops the bill.
