# Choosing (or Skipping) a Framework

> A framework is worth it when it does something hard that you need: durable state, permissions, retrieval plumbing, validated output. It isn't worth it for a loop you can write in 100 lines. Write your needs down, score the options against them with numbers you can argue with, and keep the framework in one corner of your codebase so the choice stays reversible.

**Type:** Learn
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 9 · Lessons 1–8
**Time:** ~35 minutes

## Learning Objectives

- Turn "which framework?" into a list of concrete needs and a scored comparison, including "no framework".
- Explain why the scores are opinions, and how to replace them with your team's.
- Audit a codebase for framework lock-in by parsing its imports.
- Structure an app so the framework lives in one module and business logic stays portable.

## The Problem

Framework choices are usually made by popularity or by whoever wrote the first prototype. Six months later the team is debugging a framework abstraction they didn't need, or rewriting a hand-rolled loop to add durable state they did need. Either way, the decision was never written down, so it can't be revisited.

You've now built the core of seven frameworks by hand. You know what each one adds. This lesson turns that knowledge into a repeatable decision and a way to keep it cheap to change your mind.

## The Concept

**Start from needs, not frameworks.**

| Need | Hard to hand-roll? | Who's strong at it (Lessons 2–8) |
|------|--------------------|----------------------------------|
| Durable state, resume after crashes | Yes: checkpoints, threads, replay | LangGraph |
| Human approval before risky actions | Medium | LangGraph interrupts, Claude Agent SDK permissions |
| Multi-agent handoffs or teams | Medium | Agents SDK, CrewAI, AutoGen, LangGraph |
| Retrieval over many knowledge bases | Yes, if you need loaders and indexes | LlamaIndex |
| Typed, validated output with retries | Medium | Pydantic AI, Agents SDK |
| File editing and shell in a repo | Yes, to do it safely | Claude Agent SDK |
| Switching model providers | Easy with an OpenAI-compatible endpoint | most, except provider-specific SDKs |

**Count what you take on.** Every framework adds dependencies, upgrade churn, its own vocabulary, and a layer between you and the prompts. Lessons 3, 5, 7 and 8 each had a surprise that only showed up when we read the real prompts or ran the real library. That cost is real, and it belongs in the score.

**The rule this lesson encodes:** pick a framework only if it beats a hand-rolled loop by a clear margin on *your* needs. Otherwise, write the loop.

**Keep it reversible.**

| Layer | Framework imports? | Why |
|-------|--------------------|-----|
| Tools / business logic | No | Plain functions port to any framework |
| Agent wiring | Yes, only here | One file to rewrite if you switch |
| API / UI | No | Talks to your own interface, not framework types |

## Build It

```bash
cd code
python3 main.py
python3 main.py --needs durable_state human_approval --avoid-deps
python3 main.py --audit path/to/your/repo
```

### Step 1: write the opinions down

```python
# 0 = you build it yourself, 1 = supported, 2 = a core strength. Opinions, not benchmarks.
CAPABILITIES = {
    "no framework": {"durable_state": 0, "human_approval": 1, ...},
    "LangGraph":    {"durable_state": 2, "human_approval": 2, ...},
    ...
}
```

These numbers come from what we built and ran in Lessons 2–8. They are deliberately coarse, and they will age. The point isn't that they're right. The point is that they're **written down**, so your team can disagree with a specific number instead of a vibe.

### Step 2: score, with "no framework" as the baseline

```python
def recommend(needs, avoid_deps=False, margin=2.0):
    ranked = score(needs, avoid_deps)
    baseline = next(s for s in ranked if s.option == "no framework")
    best = next(s for s in ranked if s.option != "no framework")
    if best.total - baseline.total < margin:
        return "skip the framework ...", ranked
```

### Step 3: three example projects

```text
support bot: refunds need approval, must survive restarts
  needs: durable_state, human_approval
       4  LangGraph          strong at durable_state; strong at human_approval
       3  Claude Agent SDK   strong at human_approval
       2  OpenAI Agents SDK  
  -> use LangGraph: +3 over a hand-rolled loop

one agent that extracts typed invoices, few dependencies
  needs: typed_output + avoid dependencies
       1  no framework       
       1  OpenAI Agents SDK  strong at typed_output; dependency weight -1
       1  Pydantic AI        strong at typed_output; dependency weight -1
  -> skip the framework: the best option (OpenAI Agents SDK) beats a hand-rolled loop by only 0 point(s)

automation that edits a repo and runs tests
  needs: file_and_shell, human_approval
       4  Claude Agent SDK   strong at file_and_shell; strong at human_approval
       2  OpenAI Agents SDK  
       2  LangGraph          you build file_and_shell; strong at human_approval
  -> use Claude Agent SDK: +3 over a hand-rolled loop
```

The middle case is the important one. One typed extraction with a strict dependency budget: Pydantic AI is good at typed output, but Lesson 8's ~150-line `Agent` already does validate-and-retry. Skipping is a legitimate answer, and the tool says so.

### Step 4: audit lock-in

`audit()` parses every `.py` file with `ast` (it never imports or runs them), finds framework imports, and counts every use of an imported name:

```text
lock-in audit of sample_app/: 3 Python files
  agent.py       imports LangGraph
  api.py         imports LangGraph
  portable (no framework imports): tools.py
  framework surface: 6 symbols, 6 uses
      1  LangGraph.StateGraph
      1  LangGraph.START
      1  LangGraph.tools_condition
      1  LangGraph.ToolNode
      1  LangGraph.InMemorySaver
      1  LangGraph.END
```

`tools.py` is clean. `agent.py` is where the framework should be. But `api.py` imports `END` and builds LangGraph's `{"configurable": {"thread_id": ...}}` config itself, so the framework has leaked into the HTTP layer. Switching frameworks now means editing two files instead of one. That leak is what the audit is for.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

A decision record you can paste into your repo:

| Field | Example |
|-------|---------|
| Needs (ranked) | durable_state, human_approval |
| Options scored | no framework 1, LangGraph 4, Claude Agent SDK 3 |
| Decision | LangGraph |
| Why not hand-rolled | Checkpointing and interrupt/resume would be ~500 lines we'd maintain |
| Boundary | Only `agent.py` imports LangGraph; tools and API don't |
| Revisit when | We stop needing durable state, or the framework's major version changes |

## Ship It

`outputs/skill-framework-decision.md` is a skill that runs this process for a real project: list needs, score options including "no framework" with stated opinions, recommend or recommend skipping, audit any existing code for lock-in, and write a one-page decision record.

## Exercises

1. **Easy.** Run `--audit` on a repository you work on. Which files import a framework? Which shouldn't?
2. **Medium.** Change three numbers in `CAPABILITIES` that you disagree with, based on your own experience in Lessons 2–8. Does any example's recommendation change?
3. **Medium.** Fix `sample_app/api.py` so it no longer imports LangGraph: give `agent.py` a `run(user, text)` function that hides the config shape. Re-run the audit.
4. **Hard.** Add a `team_knows` input that adds +1 to frameworks your team already uses, and a `maturity` penalty for frameworks with a major release in the last 6 months. Write down where those numbers come from.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Lock-in | "We're stuck with X" | How much code you'd have to change to switch, measured by imports and symbols used |
| Framework surface | "How much of X we use" | The distinct framework names your code references |
| Boundary module | "Adapter" | The one place framework code is allowed to live |
| Decision record | "ADR" | A short written record of a choice, its reasons and when to revisit it |
| Baseline | "Do nothing" | The hand-rolled loop every framework must beat |

## Further Reading

- [Anthropic, Building effective agents (2024)](https://www.anthropic.com/engineering/building-effective-agents), especially the section "When and how to use frameworks"
- [Michael Nygard, Documenting architecture decisions (2011)](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
- [Alistair Cockburn, Hexagonal architecture](https://alistair.cockburn.us/hexagonal-architecture/)
- [Kapoor et al., AI Agents That Matter (2024)](https://arxiv.org/abs/2407.01502)
