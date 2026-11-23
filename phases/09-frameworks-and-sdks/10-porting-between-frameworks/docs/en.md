# Porting Between Frameworks

> A port isn't done when the new code runs. It's done when the new code makes the same tool calls with the same arguments on the same inputs. Describe the agent once in a framework-neutral spec, generate each framework's code from it, then replay recorded model replies through the old and new runtimes and diff the trajectories. Checking only final answers will pass a port that is badly broken.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 9 · Lessons 2, 3, 8 and 9; Phase 3 · The agent loop in 120 lines
**Time:** ~45 minutes

## Learning Objectives

- Write a framework-neutral agent spec: instructions, tools, approvals, output fields and budget.
- Generate Pydantic AI, OpenAI Agents SDK and LangGraph code from the spec, carrying approvals and budgets across.
- Replay recorded model replies through two runtimes and find the first divergence in their trajectories.
- Explain why final-answer comparison misses porting bugs, and why framework-added prompt text needs a behaviour check.

## The Problem

You're moving an agent from a hand-written loop to a framework, or from one framework to another. The port compiles, the demo question gives the right answer, and you ship it. A week later finance notices refunds stopped going out. The new tool schema used `orderId`, the function still took `order_id`, every refund call failed, and the model politely told customers their refund was processed.

Porting bugs hide in the space between the model and your functions: parameter names, defaults, approval flags, turn budgets, extra instructions the framework adds to your prompt. You need a check that looks at what the agent *did*, not just what it *said*.

## The Concept

**Three steps for a safe port:**

| Step | Artifact | Catches |
|------|----------|---------|
| 1. Spec | `AgentSpec`: instructions, tools with params and approval flags, output fields, `max_turns` | Forgotten approvals and budgets |
| 2. Generate | Framework code from the spec, checked to parse | Hand-copy mistakes, inconsistent schemas |
| 3. Parity | Replay recorded runs through old and new; diff trajectories | Renamed params, changed tool behaviour, early stops |

**What a trajectory contains:** every tool call with its arguments (keys sorted), every tool result, and the final answer. Two runs match when every line matches.

**Concept mapping you'll need when porting:**

| Concept | Hand-written | Pydantic AI | OpenAI Agents SDK | LangGraph |
|---------|--------------|-------------|-------------------|-----------|
| Instructions | system message | `instructions=` | `instructions=` | `prompt=` |
| Tool | function + schema | `@agent.tool_plain` | `@function_tool` | `@tool` |
| Approval | your gate | deferred tools | `needs_approval=True` | interrupt before tools |
| Typed output | your validator | `output_type=` | `output_type=` | structured response / your node |
| Budget | `max_turns` | `UsageLimits(request_limit=)` | `max_turns=` | `recursion_limit` (≈ 2 × turns + 1) |

## Build It

```bash
cd code
python3 main.py
python3 main.py --emit pydantic_ai     # print the generated code for one framework
```

### Step 1: one spec

```python
SPEC = AgentSpec(
    name="refund_agent",
    instructions="Decide refunds. Look the order up first. Never refund more than was paid.",
    tools=[ToolSpec("lookup_order", "Look up an order by id.", {"order_id": "string"}, lookup_order),
           ToolSpec("issue_refund", "Refund an order.", {"order_id": "string", "amount": "number"}, issue_refund,
                    needs_approval=True)],
    output_fields={"order_id": "string", "refunded": "boolean", "amount": "number"},
)
```

The business functions (`lookup_order`, `issue_refund`) stay plain Python, so the generated code imports them from `impl` instead of copying them.

### Step 2: generate and check

```text
1. generate code from one spec
  pydantic_ai     30 lines, parses OK, functions: lookup_order, issue_refund, run
  openai_agents   29 lines, parses OK, functions: lookup_order, issue_refund, run
  langgraph       28 lines, parses OK, functions: lookup_order, issue_refund, build, run
```

The tests also check that approvals and budgets survive: `@function_tool(needs_approval=True)` on `issue_refund`, `request_limit=8`, `max_turns=8`, `recursion_limit` 17.

We went further and imported all three generated files against the real libraries (`pydantic-ai-slim` 2.71.0, `openai-agents` 0.25.0, `langgraph` 1.2.24). Two things came out of that:

1. The first LangGraph generator referenced an undefined global `model`. `ast.parse` can't catch that; only importing and running can. The generator now emits `build(model)`.
2. LangGraph 1.x warns: `create_react_agent has been moved to langchain.agents. Please update your import to from langchain.agents import create_agent.` APIs move between versions. Pin versions, and re-run parity after every upgrade.

### Step 3: replay and diff

```python
def parity(spec, task, cassette, buggy_port=False):
    src = run_source(spec, task, replaying(cassette))
    tgt = run_target(spec, task, replaying(cassette, follow_schema), buggy_port)
    a, b = trajectory(src), trajectory(tgt)
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), ...)
```

The cassette holds model replies recorded from the source agent. `follow_schema` makes the replay behave like a real model reading the *new* schema: if the schema says `orderId`, the model sends `orderId`.

### Step 4: a faithful port

```text
  faithful port: PARITY OK
     call lookup_order {"order_id": "A-1001"}                         |  call lookup_order {"order_id": "A-1001"}
     result {"item": "headphones", "total": 79.0}                     |  result {"item": "headphones", "total": 79.0}
     call issue_refund {"amount": 79.0, "order_id": "A-1001"}         |  call issue_refund {"amount": 79.0, "order_id": "A-1001"}
     result refunded $79.00 on A-1001                                 |  result refunded $79.00 on A-1001
     answer {"order_id": "A-1001", "refunded": true, "amount": 79.0}  |  answer {"order_id": "A-1001", "refunded": true, "amount": 79.0}
  system prompt diff (frameworks add their own instructions; re-check behaviour, not just code):
    @@ -1,0 +2 @@
    +When you have the final answer, reply with JSON only.
```

Parity holds, but the prompt diff is a warning. The target runtime added an instruction, as most frameworks do (Lessons 5 and 7 showed real examples). Replay can't tell you whether a live model behaves differently with the extra text. Run a small live eval after the replay passes (Phase 11).

### Step 5: the bug from the story

```text
  port with camelCase tool params: DIVERGED at step 0
  !! call lookup_order {"order_id": "A-1001"}                         |  call lookup_order {"orderId": "A-1001"}
  !! result {"item": "headphones", "total": 79.0}                     |  result error: TypeError: lookup_order() got an unexpected keyword argument 'orderId'. Did you mean 'order_id'?
  !! call issue_refund {"amount": 79.0, "order_id": "A-1001"}         |  call issue_refund {"amount": 79.0, "orderId": "A-1001"}
  !! result refunded $79.00 on A-1001                                 |  result error: TypeError: issue_refund() got an unexpected keyword argument 'orderId'. Did you mean 'order_id'?
     answer {"order_id": "A-1001", "refunded": true, "amount": 79.0}  |  answer {"order_id": "A-1001", "refunded": true, "amount": 79.0}
```

Look at the last line: **the final answers match.** A check that compares only answers passes this port, while every tool call failed and no refund was issued. The answer here is replayed, but a live model does the same thing often enough: it reports success it didn't achieve. Compare trajectories.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Porting step | Practical advice |
|--------------|------------------|
| Record | Log real runs' model replies and tool calls (Phase 11 · Replay and regression); 20–50 cover most paths |
| Spec | Keep the spec in your repo even after the port; it documents the agent |
| Generate | Generate once, then edit by hand; the parity suite protects the edits |
| Parity | Run replay parity in CI on every change and every framework upgrade |
| Live check | After parity passes, run a small live eval, since framework prompt text changes behaviour |
| Cut over | Shadow traffic: run both, compare trajectories, switch when they agree |

## Ship It

`outputs/skill-framework-port.md` is a skill for planning and verifying a port: extract a spec from the existing agent, map each concept to the target framework, generate code, record a cassette, run trajectory parity, review the framework's added prompt text, and run a live eval before cutting over.

## Exercises

1. **Easy.** Add a third tool, `get_customer(email)`, to the spec. Check that all three generators pick it up.
2. **Medium.** Introduce a different porting bug: the target's `issue_refund` defaults `amount` to the order total when it's missing. Write a cassette that catches it.
3. **Medium.** Write `extract_spec()`, which reads Phase 3's `ToolRegistry` and builds an `AgentSpec` from it.
4. **Hard.** Replace `run_target` with the real `with_pydantic_ai.py` from Lesson 8 using `FunctionModel` to replay the cassette, and run parity between the hand-written loop and real Pydantic AI.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Agent spec | "Config" | A framework-neutral description of instructions, tools, approvals, output and budget |
| Cassette | "Recorded run" | Model replies saved from real runs, replayed in order |
| Trajectory | "What the agent did" | The ordered tool calls, arguments, results and final answer |
| Parity | "Same behaviour" | Identical trajectories on the same replayed inputs |
| First divergence | "Where it broke" | The first step where the two trajectories differ |
| Shadow traffic | "Run both" | Sending real requests to old and new versions and comparing, before switching |

## Further Reading

- [Martin Fowler, Strangler Fig Application](https://martinfowler.com/bliki/StranglerFigApplication.html)
- [LangGraph releases (changelog and deprecations)](https://github.com/langchain-ai/langgraph/releases)
- [OpenAI Agents SDK: tools](https://openai.github.io/openai-agents-python/tools/)
- [Pydantic AI: testing](https://ai.pydantic.dev/testing/)
- [VCR.py: record and replay HTTP interactions](https://vcrpy.readthedocs.io/)
