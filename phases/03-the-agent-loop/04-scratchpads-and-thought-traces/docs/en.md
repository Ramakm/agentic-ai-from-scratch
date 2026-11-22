# Scratchpads and Thought Traces

> Reasoning is for the agent and for you. The user gets the answer. Decide where each thought lives, and check the model can actually use it.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lessons 1–3
**Time:** ~40 minutes

## Learning Objectives

- Name three places an agent's reasoning can live: inline thoughts, a `think` tool, and a pinned scratchpad of notes.
- Keep a developer-only thought trace separate from the user-facing answer, and strip reasoning tags before display.
- Keep important facts available after old messages are trimmed, by pinning notes into the prompt.
- Measure whether a model actually uses these tools, and find out why when it doesn't.

## The Problem

In ReAct (Lesson 2), every step begins with a written `Thought:`. Native tool calling doesn't require one: a model can go straight from question to tool call with no visible reasoning. That's efficient, but you lose two things. The model loses a place to plan ("I need both heights, then the difference, then feet"). And you lose the record of *why* it did what it did, which is what you need when it goes wrong.

The opposite failure is just as common: reasoning leaks into the answer. The user asks a question and gets back "<thinking>Round to the nearest foot.</thinking> Everest is about 781 ft taller".

And long runs have a third problem. Lesson 11 trims old messages to save tokens. If the Everest height was looked up at step 2 and step 2 has been trimmed, the agent has forgotten it, and will look it up again, or worse, guess.

## The Concept

### Three places for reasoning

| Where | How | Survives trimming? | Seen by user? |
|-------|-----|-------------------|---------------|
| **Inline** | Text the model writes in `content` next to its tool calls | Only while the message is kept | No (goes to the trace) |
| **Think tool** | `think(thought)`, a tool that does nothing and returns "ok" | Only while the message is kept | No |
| **Scratchpad notes** | `note(key, value)`, pinned into the system prompt every turn | **Yes** | No |

The `think` tool idea comes from Anthropic's engineering blog: give the model an explicit, cheap place to stop and reason between tool calls, which helped most in long tool chains with policies to follow.

### Two audiences

| Audience | Gets | How |
|----------|------|-----|
| User | The answer | `for_user()` strips `<thinking>…</thinking>` and tidies whitespace |
| Developer | Every thought, with step number and source | `Scratchpad.trace`: a list of `Thought(step, source, text)` |

## Build It

```bash
cd code
python3 main.py
```

```text
thought trace (for developers):
  step 1  think   I need both heights in metres, the difference, then convert to feet.
  step 2  inline  Looking up Everest first.
  step 7  think   238 m difference; 780.84 ft. Plausible: about a quarter km.
  step 8  tag     Round to the nearest foot.

pinned notes: {'everest_m': '8849', 'k2_m': '8611'}

answer (for the user): Everest is about **781 ft** taller than K2 (8,849 m vs 8,611 m).
```

The demo runs with `keep_last=4`: the model sees only the last four messages, yet both heights stay in view as pinned notes.

### Step 1: `Scratchpad`

`think()` appends to the trace and returns `"ok"`; it changes nothing else. `note()` stores a fact. `pinned()` renders all notes as a `<notes>` block. Both `think` and `note` are offered to the model as ordinary tools, with descriptions that say what they're for.

### Step 2: Notes pinned every turn

Before each model call, the loop rebuilds the system message as `SYSTEM + pad.pinned()`. The message history can be trimmed however you like; the notes are re-rendered from the scratchpad every turn. `test_notes_survive_trimming` checks that the looked-up "8849 metres" is gone from the trimmed view while `everest_m: 8849` is still in the system prompt.

`trim()` keeps the system message, the task, and the last *N* messages, and never starts the tail on a `tool` message, because a tool result without the assistant call that requested it is rejected by most APIs.

### Step 3: Collecting the trace

Three sources feed `pad.trace`: `think` calls, text written next to tool calls (`inline`), and `<thinking>` tags anywhere in a reply (`tag`). The final answer passes through `for_user()`. The trace is for logs, tracing (Phase 0 · Lesson 7) and debugging; it never goes to the user.

### Step 4: Does a real model use the think tool?

```bash
python3 main.py --trials 10      # llama3.2, temperature 0.8, notes off
```

```text
without think tool  correct 0/10  avg steps 2.0  think calls 0  successful lookups 0
with think tool     correct 0/10  avg steps 2.0  think calls 0  successful lookups 0
```

`llama3.2` never called `think`. And every single run took **exactly 2 steps**: one tool call (often the calculator with words in it, like `"Mount Everest height in feet - K2 height in feet"`), then an answer from memory. An earlier batch scored 1/10 with the tool and 0/10 without, with the same pattern.

Exactly 2 steps every time is a clue, not a coincidence. Lesson 11 found the cause in `llama3.2`'s chat template: it lists the tools only alongside the **last user message**. After the first tool result, the last message is a tool message, and the model sees no tools at all. Every run gets one tool-visible turn. Spending it on `think` would mean never calling a real tool.

### Step 5: Keep the tools visible

`keep_tools_visible(llm)` wraps the model: when the last message is a tool result, it appends one user turn, "Continue: call another tool, or give the final answer.", to **the request only**, not the stored history.

```bash
python3 main.py --trials 10 --reprompt
```

```text
without think tool  correct 0/10  avg steps 10.0  think calls 0  successful lookups 1
with think tool     correct 0/10  avg steps 10.0  think calls 0  successful lookups 2
```

The fix worked mechanically: the model kept calling tools, and every run now used its whole 10-step budget. But it still never called `think`, and it still never got the answer. A transcript shows why:

```text
  lookup {"topic":"Mount Everest height vs K2 height"}
    <- no entry for 'Mount Everest height vs K2 height'. Try e.g. '
  lookup {"topic":"height of Mount Everest vs K2"}
  ...
  lookup {"topic":"K2 height"}
    <- 8611 metres
  lookup {"topic":"height of Mount Everest vs K2"}
```

Our `lookup` only matches exact topics, and the model kept asking for both mountains at once, repeating itself. Once, it followed the tool's hint (`Try e.g. 'K2 height'`) and got a real result, then went back to the combined query.

That's three findings stacked on each other:

1. The think tool's value depends on the model. This 3B model never used it in more than 30 runs where it was offered.
2. A chat template can hide the tools after the first call. Check yours before blaming the model.
3. Fixing visibility exposed the next bottleneck: a brittle exact-match tool, and a loop that repeats itself (Lesson 12's patterns). Each fix needs its own measurement.

The scratchpad mechanics (pinned notes, trimming, the clean answer) are code, and the tests prove they work. Whether a given model makes good use of them is an empirical question, so measure it.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: trace sources, clean answers, the think tool changing nothing, notes surviving trimming, trimming never starting on a tool result, disabled tools not being offered, `think` as an unknown tool when disabled, `keep_tools_visible` not touching the real history, and the answer checker.

## Use It

| Feature | Where you'll see it |
|---------|---------------------|
| Extended thinking | Claude models: reasoning blocks returned separately from the answer, with a token budget |
| Reasoning models | OpenAI o-series and GPT-5 reasoning: reasoning happens before the reply; summaries are optional |
| `<think>` tags | DeepSeek-R1, Qwen3 and other open models write reasoning in tags you strip before display |
| Think tool | Anthropic's documented pattern: a no-op tool for reasoning between tool calls |
| Scratchpad / memory tools | LangGraph state keys, OpenAI Agents SDK context, Claude memory tool |

When a model has built-in reasoning, you mostly need the *trace* half of this lesson: log reasoning separately, never show raw reasoning to users, and budget its tokens.

## Ship It

`outputs/skill-agent-scratchpad.md` is a skill that adds a scratchpad to an agent: pinned notes, a developer-only thought trace, answer cleaning, and a check of the chat template's tool rendering.

## Exercises

1. **Easy.** Make `lookup` forgiving: match if the stored topic's words are all in the request (`"height of K2"` contains `k2` and `height`). Re-run `--trials 10 --reprompt`. Does accuracy move?
2. **Medium.** Add a `plan(steps)` tool that stores a checklist in the scratchpad, and a `check(step)` tool. Pin the checklist with `[x]` and `[ ]` marks.
3. **Medium.** Add Lesson 12's watchdog to this loop. Does nudging after repeated lookups help `llama3.2` find the right topic?
4. **Hard.** Run the trials against a hosted model with native reasoning (set `AGENT_BASE_URL` and `AGENT_MODEL`). Does it call `think`? Does `keep_tools_visible` matter for it?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Scratchpad | "Agent memory" | Notes the agent writes and reads back, kept outside the message history |
| Thought trace | "Reasoning log" | Every recorded thought, with step and source, for developers only |
| Think tool | "Reasoning tool" | A no-op tool whose call gives the model a place to reason between actions |
| Pinned context | "Sticky notes" | Content re-inserted into the prompt every turn so trimming can't remove it |
| Chat template | "Prompt format" | How messages and tools become the model's token sequence; it decides what the model actually sees |

## Further Reading

- [Anthropic, *The "think" tool: enabling Claude to stop and think in complex tool use situations*](https://www.anthropic.com/engineering/claude-think-tool)
- [Anthropic, Extended thinking](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking)
- [Nye et al., *Show Your Work: Scratchpads for Intermediate Computation with Language Models* (2021)](https://arxiv.org/abs/2112.00114)
- [Ollama, Modelfile `TEMPLATE` reference](https://github.com/ollama/ollama/blob/main/docs/modelfile.md#template)
