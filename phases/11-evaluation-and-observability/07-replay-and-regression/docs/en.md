# Replay and Regression

> Record a run once (every model reply and every tool result) and you can re-run it forever: no API cost, no network, no refunds issued twice. Replay strictly and you'll know the moment anything you send the model changes. Replay leniently through a new version and you'll see the first step where it acts differently. That turns "I only refactored" into something you can check in CI.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 11 · Trajectory evaluation; Phase 9 · Porting between frameworks; Phase 2 · Idempotency and side effects
**Time:** ~45 minutes

## Learning Objectives

- Record model calls (with a hash of each request) and tool results into a cassette file.
- Replay a cassette with no network and no side effects, keyed by call order for the model and by arguments for tools.
- Use strict replay to detect request drift, and lenient replay to find behavioural divergence in the agent's own code.
- Know what replay can't tell you, and when you need a live eval instead.

## The Problem

You refactor the code between the model and your tools: tidy up argument handling, add a helper, rename a variable. The unit tests pass. You can't afford to run the full live eval on every commit (it costs money and takes 20 minutes), and when you do run it, it's noisy (Lesson 1). So the refactor ships, and a week later finance notices refunds of $26 on $25.50 orders.

Live evals are the wrong tool for "did my refactor change behaviour?". The model's replies vary, so differences hide in noise. What you need is to hold the model's side *fixed* (exactly what it said last time) and check whether *your* code still does the same thing with it.

## The Concept

| Mode | Model replies | Request check | Tool results | Use it for |
|------|---------------|---------------|--------------|------------|
| Record | live | — | live (side effects happen) | Creating cassettes from good runs |
| Strict replay | recorded, in order | request hash must match | recorded, by (tool, args) | Refactors that must not change prompts or context |
| Lenient replay | recorded, in order | ignored | recorded, by (tool, args) | Code changes between model and tools |
| Live eval (Lessons 1–5) | live | — | live or sandboxed | Prompt, model or behaviour changes |

**What a cassette holds:** the task; for each model call, a hash of the exact request (messages + tool schemas) and the reply; for each tool call, the name, arguments and result.

**Tools are replayed by arguments, not order.** If the new code calls `issue_refund(amount=26)` where the recording has `amount=25.5`, there's no recorded result. The replay says so instead of running the real tool. That's both the safety property (nothing real happens) and the detection signal.

## Build It

```bash
cd code
python3 main.py
```

The demo records three tasks with version 1 of a small refund agent, then replays them through three versions.

### Step 1: record

```python
def rec_llm(messages, schemas):
    reply = llm(messages, schemas)
    cas.model_calls.append({"request": request_hash(messages, schemas), "reply": reply})
    return reply
```

Recording issues two real refunds, which is the reason to record once and replay ever after.

### Step 2: replay

```python
if strict and request_hash(messages, schemas) != rec["request"]:
    raise ReplayError(f"request drift at model call {i}: what we send the model changed since recording")
```

Tool replay looks results up by `(name, sorted JSON args)`. An unrecorded call returns an error string, and the real function never runs.

### Step 3: three versions

```text
recorded 3 cassettes; real refunds issued while recording: 2

v1, strict replay:
  same      Refund A-1001
  same      Refund B-2002
  same      Status of Z-9

v2 prompt edit, strict replay:
  drift     Refund A-1001   request drift at model call 1: what we send the model changed since recording
  drift     Refund B-2002   request drift at model call 1: what we send the model changed since recording
  drift     Status of Z-9   request drift at model call 1: what we send the model changed since recording

v2 prompt edit, lenient replay:
  same      Refund A-1001
  same      Refund B-2002
  same      Status of Z-9

v3 refactor, lenient replay:
  diverged  Refund A-1001   step 2: recorded {"args": {"amount": 79.0, "order_id": "A-1001"}, ...}
                 now      {"args": {"amount": 79, "order_id": "A-1001"}, "result": "error: replay has no recorded result for issue_refund(...)", ...}
  diverged  Refund B-2002   step 2: recorded {"args": {"amount": 25.5, "order_id": "B-2002"}, ...}
                 now      {"args": {"amount": 26, "order_id": "B-2002"}, "result": "error: replay has no recorded result for issue_refund(...)", ...}
  same      Status of Z-9

real refunds issued during all replays: 0
```

What each block teaches:

- **v1 strict:** replay is deterministic. Same code, same results, zero side effects.
- **v2 strict:** one word added to the system prompt ("politely") is caught at the first model call. Strict replay is a tripwire for refactors that were never supposed to touch what the model sees.
- **v2 lenient: "same" doesn't mean the prompt change is safe.** The model's replies are the recorded ones, so lenient replay *can't* show how the model reacts to the new prompt. Prompt changes need a live eval (Lessons 1–5).
- **v3 lenient:** the refactor's `round(amount)` is caught at step 2 of both refunds. B-2002 is the real bug: 25.5 became 26. A-1001 is subtler: 79.0 became the integer 79. It's numerically equal, but the replay key is the JSON of the arguments, and `79` and `79.0` serialise differently. Whether that's a bug depends on your tool (some APIs reject integers where they expect decimals). Either way, the replay key must normalise exactly as strictly as your tools do.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Tool | What it does |
|------|--------------|
| VCR.py, pytest-recording | Record and replay HTTP interactions, including model API calls |
| Framework test models (Agents SDK `ScriptedModel`, Pydantic AI `FunctionModel`, AutoGen replay client) | Script or replay model replies in tests (Phase 9) |
| Trace-based replay in observability platforms | Re-run a production trace's inputs against a new version |
| Phase 9 · Porting between frameworks | The same idea applied to a framework port |

A practical regression setup: record cassettes from 20–50 good runs (production traces are ideal), run strict replay on every commit that shouldn't touch prompts, lenient replay on every commit, and a live eval nightly or before release.

## Ship It

`outputs/skill-replay-regression.md` is a skill for setting up record/replay regression tests for an agent: what to record, where cassettes live, strict vs lenient modes per kind of change, argument normalisation for tool replay, and how to refresh cassettes when behaviour is supposed to change.

## Exercises

1. **Easy.** Normalise numbers in the tool replay key (`79` and `79.0` match). Re-run: which divergences remain?
2. **Medium.** Add a "refresh" command that re-records a cassette with the live model and prints a trajectory diff against the old one, for when a change is intended.
3. **Medium.** Make strict mode report *what* drifted: diff the recorded and current requests (store the full request in the cassette, not just its hash). What are the privacy implications of storing full prompts?
4. **Hard.** Record 10 runs of Phase 10's mini coding agent with a real model, then refactor its `edit_file` tool and use lenient replay to prove the refactor is behaviour-preserving.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Cassette | "Recording", "fixture" | A file of recorded model replies and tool results for one run |
| Replay | "Playback" | Re-running the agent with recorded replies instead of live calls |
| Request drift | "Prompt changed" | What's sent to the model differs from what was recorded |
| Strict replay | "Exact replay" | Replay that fails if any request differs |
| Lenient replay | "Behavioural replay" | Replay that serves recorded replies regardless of request, to test your own code |
| Regression | "It used to work" | A change that makes previously correct behaviour wrong |

## Further Reading

- [VCR.py documentation](https://vcrpy.readthedocs.io/)
- [pytest-recording](https://github.com/kiwicom/pytest-recording)
- [Martin Fowler, Self-testing code](https://martinfowler.com/bliki/SelfTestingCode.html)
- [Pydantic AI: testing with FunctionModel and TestModel](https://ai.pydantic.dev/testing/)
