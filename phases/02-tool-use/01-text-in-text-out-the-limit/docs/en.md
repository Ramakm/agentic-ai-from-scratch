# Text In, Text Out: The Limit

> A model can only produce text from what it learned and what you send it. It can't look up today's date, compute a hash exactly, read your database, or do anything. Tools are how it gets past each of those limits.

**Type:** Learn
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 1 · Lessons 1, 4 and 10
**Time:** ~30 minutes

## Learning Objectives

- Name the four things a model can't do from text alone: exact computation, fresh data, private data, and actions.
- Run one tool round trip by hand: the model requests a tool, your code runs it, the model answers from the result.
- Measure the difference tools make on questions of each kind.
- Spot the worst failure without tools: a confident, made-up answer, including made-up *actions*.

## The Problem

Ask a model "Open a support ticket titled 'Broken teapot' and tell me its id." Without tools, llama3.2 replied:

```text
The support ticket ID is #TS-001.
```

No ticket exists. Nothing happened. The model produced the most likely text for that request, and that text claims an action took place. The same goes for a SHA-256 hash it can't compute (it printed a plausible-looking wrong one) and an order it can't see.

These aren't failures of intelligence. A model's only input is the prompt, and its only output is text. Anything that needs the outside world needs a tool.

## The Concept

### Four limits, four kinds of tool

| Limit | Example question | Tool |
|-------|------------------|------|
| Exact computation | Days between two dates; a SHA-256 hash | `days_between`, `sha256` |
| Fresh data | Today's date | `today` |
| Private data | The status of order A-1001 | `order_status` |
| Actions | Open a support ticket | `create_ticket` |

### One round trip

| Turn | Who | What |
|------|-----|------|
| 1 | You → model | The question, plus tool definitions |
| 1 | Model → you | A tool call: name and arguments, not an answer |
| — | Your code | Runs the tool |
| 2 | You → model | The question, the model's call, and the tool's result |
| 2 | Model → you | The final answer, built from the result |

That's tool calling. Phase 3 put this in a loop; this lesson does exactly one round trip, so every step is visible.

## Build It

```bash
cd code
python3 main.py           # scripted model
python3 main.py --live    # llama3.2
```

### Step 1: The tools

Five small functions, one or two per limit. `create_ticket` appends to a list, so you can count real side effects.

### Step 2: `answer_with_one_tool`

Send the question with `SCHEMAS`. If the reply has `tool_calls`, run each with `run_tool` (which accepts arguments as a dict or a JSON string and turns failures into strings), append the assistant's call and the tool results, and ask again.

### Step 3: Three conditions, measured

For each question: no tools at all; one round trip where the final request sends no tools; and one round trip where the final request still includes the tool definitions.

```text
[action] Open a support ticket titled 'Broken teapot' and tell me its id.   tool used: ['create_ticket']
   no tools                fail  'The support ticket ID is #TS-001.'
   tool, plain final turn  PASS  'The ID of the support ticket is T-101.'
   tool, tools kept        PASS  'The ID of the newly created support ticket is T-102. The title of the ticket is '

no tools 0/6 | one tool, final turn without tools 3/6 | one tool, tools kept on final turn 5/6 | tickets actually created: 2
```

1. **Without tools: 0/6.** Two failures were confident inventions (a SHA-256 hash and a ticket id), one explained how you *would* compute the days instead of answering, and three said it couldn't know.
2. **The model always picked the right tool.** Every question triggered the correct call with correct arguments. Choosing tools was the easy part.
3. **With tools, the final turn decided the result: 3/6 versus 5/6.**

### Step 4: The model disowned its own tool results

With the plain final turn, two answers were remarkable. The model called the tool, received the right result, then wrote:

```text
I'm a large language model, I don't have real-time access to the current date and time. My previous response was an error on my part.
```

```text
I don't have real-time access to order tracking information. The status I provided earlier was fictional.
```

It treated the tool's output as something *it* had made up. Lesson 1.4 explains why. llama3.2's chat template only adds the system line *"When you receive a tool call response, use the output to format an answer to the orginal user question"* when tools are present in the request. Our first version sent the final request without tools, so the model saw its own JSON tool call and an `ipython` result with no explanation of what they were.

Sending the tool definitions on the final turn too (`tools_on_final=True`) fixed both, and the SHA-256 answer as well: 5/6. The remaining failure is a format slip, the right date written as `11/23/2026` instead of `YYYY-MM-DD`.

The general lesson: what the model sees on every turn depends on the template *and* on what you send. Keep the request shape consistent across turns.

### Step 5: Tools really act

`tickets actually created: 2`. Measuring the action question in two conditions created two real tickets. Testing tools that change the world has real effects, which is why Lesson 7 covers idempotency, and Lesson 11 covers testing with fakes.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eight tests: exact tool results, dict and JSON arguments, errors as strings, schemas matching tools, every question passing with one tool and failing without, the `tools_on_final` flag, and actions really happening twice when run twice.

## Use It

| Platform | Name for it |
|----------|-------------|
| OpenAI | Function calling / tools; built-in tools like web search and code interpreter |
| Anthropic | Tool use; server tools like web search and code execution |
| Google Gemini | Function calling; grounding with Google Search |
| MCP (Model Context Protocol) | A standard way to expose tools from separate servers (Phase 7) |

Hosted "built-in" tools are the same idea run by the provider: the model asks, something outside the model does the work.

## Ship It

`outputs/skill-tool-gap-finder.md` is a skill that reviews an assistant's questions or transcripts, finds the answers that needed computation, fresh data, private data or an action, and proposes the minimal tool for each, with a check that the model's final answer uses the tool's result.

## Exercises

1. **Easy.** Add a `word_count(text)` tool and a question that needs it. Does the model pick it over guessing?
2. **Medium.** Ask "What is today's date and how many days until 2026-12-31?" The answer needs two tools, one after the other. What does one round trip get wrong?
3. **Medium.** Change `create_ticket` to return `{"id": "T-101", "url": "..."}` as JSON. Does the final answer change?
4. **Hard.** Run the live evaluation at temperature 0.7, 5 times. Is "tools kept on the final turn" still better? By how much?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Tool | "Function" | Code the model can ask your program to run, described by a name and a schema |
| Tool call | "Function call" | The model's structured request: which tool, with which arguments |
| Round trip | "Tool use" | Model requests, code runs, model answers from the result |
| Grounded answer | "From the tool" | An answer built from tool output rather than from the model's memory |
| Side effect | "It did something" | A change in the world (a ticket, a payment) caused by running a tool |

## Further Reading

- [OpenAI, Function calling](https://platform.openai.com/docs/guides/function-calling)
- [Anthropic, Tool use overview](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview)
- [Schick et al., *Toolformer: Language Models Can Teach Themselves to Use Tools* (2023)](https://arxiv.org/abs/2302.04761)
- [Ollama, Tool support](https://ollama.com/blog/tool-support)
