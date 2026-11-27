# Subagents & Delegation

> A subagent is a function call with its own context window. The parent pays for a summary, not for everything the child had to read.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** 15.02 · The core loop & tool registry; Phase 8 · Orchestrator–worker
**Time:** ~60 minutes

## Learning Objectives

- Build a `task` tool that runs a fresh agent on a sub-problem and returns only its final answer.
- Define subagent profiles: a description the parent reads, a system prompt, a toolset (read-only by default), a step limit, and optionally a different model.
- Enforce the limits: a depth limit, a token budget shared with the parent, the same permission hooks, and an honest `read_only` flag on `task` itself.
- Measure what delegation changes: the parent's context per call, and the total tokens.

## The Problem

"Which functions in `inventory/` modify their arguments?" To answer, an agent lists the folder and reads four files. Every one of those reads stays in the main agent's context and is re-sent on every later call, long after it stopped being useful. By the time the agent gets back to the actual job (fixing something), a third of its context is files it has finished with.

Phase 8 showed the orchestrator–worker pattern for this. A harness needs a narrower version that's safe to hand to a model: one tool, a fixed set of worker types, limits the model can't negotiate, and a result that's just the answer.

## The Concept

### What the child gets, and what comes back

| | Parent | Child (subagent) |
|-|--------|------------------|
| Context | Its whole history | System prompt + the `prompt` argument. Nothing else |
| Tools | All | The profile's toolset; never `task` itself |
| Model | The configured one | The profile's (e.g. a cheaper one), or the parent's |
| Steps | `max_steps` | The profile's own, smaller limit |
| Budget | Shared | Shared: the child spends the same budget |
| Hooks | All | Whatever `child_hooks(profile)` returns; 15.08 passes the tracer, a context manager and the same permissions |
| Result | — | `[explorer subagent: final_answer after 6 step(s), ~3,546 tokens]` + the answer |

Because the child sees only the prompt, the prompt has to be a complete brief. The `task` tool's description says so, and the child's system prompt says the parent will see only its final answer.

### Profiles

```python
Profile("explorer", "Searches and reads the workspace to answer a focused question. Read-only. ...",
        "You are an explorer subagent. ... Report concrete facts with file:line references, in under 120 words.")
```

The description is part of the `task` tool's description, so the parent model reads it when deciding whether to delegate. `tools=None` means every read-only tool. The `task` tool is marked read-only only if *every* profile's toolset is read-only. Plan mode (15.06) trusts that flag, so it has to be honest.

### Limits

| Limit | How |
|-------|-----|
| No recursion | `task` is removed from every child toolset, and the `Delegator` hook blocks `task` at depth ≥ `max_depth` |
| No escaping the budget | One `Budget` object shared by parent and children |
| No escaping permissions | Pass the parent's `Permissions` instance in `child_hooks` (15.08's `app.build` does) |
| A failed child | Comes back as an error result with its stop reason and partial answer, not as a crash |

## Build It

```bash
cd code
python3 main.py
```

### Step 1: the tool and the hook

`Delegator` is both: `tool()` returns the `task` tool, and as a hook its `before_tool` records which run is calling. That way the child knows its depth and its parent's run id, which the tracer uses to nest runs in 15.07.

```python
def run(self, args):
    profile = self.profiles[args["agent"]]
    parent = self.caller
    child = Agent(profile.llm or self.llm, self.toolset(profile), system=profile.system + CHILD_RULES,
                  hooks=self.child_hooks(profile), max_steps=profile.max_steps, budget=self.budget,
                  name=profile.name)
    r = child.run(args["prompt"], depth=parent.depth + 1, parent_id=parent.run_id)
    head = f"[{profile.name} subagent: {r.stop_reason} after {r.steps} step(s), ~{r.usage.tokens:,} tokens]"
    return ToolResult(f"{head}\n{r.answer}", error=not r.ok)
```

The child's tokens go into `parent.meta["subagent_tokens"]`, so reports can show the full cost.

### Step 2: the toolset

```python
def toolset(self, profile):
    if profile.tools is None:
        keep = lambda t: t.read_only and t.name != "task"
    else:
        keep = lambda t: t.name in profile.tools and t.name != "task"
    return self.registry.subset(keep)
```

### Output

The same question answered alone and by delegating, with the same file reads in both:

```text
  alone       main agent's context per call: [36, 82, 262, 615, 920, 1226, 1285]
              last call 1,285 tokens · total spent ~4,554 tokens (incl. subagents) · final_answer
  delegating  main agent's context per call: [36, 161, 219]
              last call 219 tokens · total spent ~4,081 tokens (incl. subagents) · final_answer

  the task result the main agent got back:
    [explorer subagent: final_answer after 6 step(s), ~3,546 tokens]
    inventory/orders.py:6 add_line() appends to order['lines'] and returns the same dict, so it modifies its argument. ...
```

The main agent's last call shrank from 1,285 to 219 tokens. Total tokens also went down here, but only slightly, and that isn't guaranteed. The child re-sends *its own* growing context, and a subagent that does little work costs more than doing it inline. Delegation reliably buys a clean parent context. Whether it saves money depends on how much the parent does afterwards (exercise 4).

The limits:

```text
  explorer's tools: list_files, read_file, search
  it tried edit_file and task -> final_answer; tools it called: ['edit_file', 'task']
    [explorer subagent: final_answer after 2 step(s), ~208 tokens]
    I couldn't edit or delegate.

  shared budget of 1,500 tokens: [explorer subagent: budget after 4 step(s), ~1,805 tokens]
```

The explorer asked for `edit_file` and `task`. Neither is in its registry, so both came back as "unknown tool" observations. The budget run went past 1,500 because the budget is checked between model calls, not inside one. It stopped at the first check after the limit.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Concern | Here | Elsewhere |
|---------|------|-----------|
| Delegation tool | `task(agent, prompt)` | Claude Code's Task tool and custom subagents; OpenAI Agents SDK agents-as-tools |
| Profiles | `Profile(name, description, system, tools, max_steps, llm)` | Claude Code subagent files (name, description, tools, model) |
| Handoff vs delegation | Delegation: the parent keeps control | Agents SDK handoffs transfer control instead |
| Parallel workers | One at a time | Phase 8 · Parallel fan-out, fan-in |

## Ship It

`outputs/skill-subagent-design.md` is a skill for designing subagent profiles: when to delegate at all, what each profile's description and tools should be, how to write the brief, and how to bound cost.

## Exercises

1. **Easy.** Add a `tester` profile that can run `bash` but nothing else. What does that do to `task.read_only`, and so to plan mode?
2. **Medium.** Run several `task` calls from one reply in parallel threads, with a cap of three at once. What happens to the shared budget, and to the order of trace events?
3. **Medium.** Give the explorer a cheaper model through `Profile.llm`. Measure answer quality against cost on five questions about this repo.
4. **Hard.** Write the break-even: with a parent that makes P more calls after delegating, and a child that reads F tokens of files over S steps, when does delegation reduce total tokens? Check the formula against the numbers above.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Subagent | "Child agent" | An agent run started by a tool call, with its own context, returning only its answer |
| Profile | "Agent type" | A subagent's description, prompt, tools, limits and model |
| Brief | "The prompt" | The complete instructions a subagent gets; it sees nothing else |
| Context isolation | "Fresh context" | The child's reads never enter the parent's history |
| Depth limit | "No recursion" | How many levels of subagents may exist; 1 here |

## Further Reading

- [Anthropic, How we built our multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system)
- [Claude Code, Subagents](https://docs.anthropic.com/en/docs/claude-code/sub-agents)
- [OpenAI Agents SDK, Agents as tools and handoffs](https://openai.github.io/openai-agents-python/multi_agent/)
- [Cognition, Don't build multi-agents](https://cognition.ai/blog/dont-build-multi-agents)
