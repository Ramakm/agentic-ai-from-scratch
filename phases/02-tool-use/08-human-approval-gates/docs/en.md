# Human Approval Gates

> Decide, per call, whether a tool runs, waits for a person, or is refused. Write the rules from what the model actually does wrong, because small wrong actions are as real as big ones.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 2 · Lessons 3, 5 and 7; Phase 3 · Lesson 8
**Time:** ~45 minutes

## Learning Objectives

- Write an approval policy: a tier per tool (auto, approve, deny), argument rules that can only make a decision stricter, and deny-by-default for unknown tools.
- Show the approver an approval card with the user's request, the exact action, the reasons, and the context needed to judge it.
- Expire approvals and record every decision in an audit log.
- Measure a policy on a real model's calls, and improve it from what slipped through.

## The Problem

Phase 3 · Lesson 8 built the machinery to pause a run and resume it after a human decides. It left open the harder question: **which calls should wait?**

Ask for approval on everything and people click "approve" without reading. Ask for nothing and the agent refunds whatever it likes. The usual first answer, "approve anything over 100", sounds sensible. This lesson's live run shows what it misses.

## The Concept

### Three outcomes

| Outcome | When | What the model sees |
|---------|------|---------------------|
| run | Low-risk tier, no rule escalates it | The tool's result |
| approve | High-risk tier, or a rule escalates it | `waiting_for_approval` with the reasons; "don't call it again" |
| deny | Unknown tool, or a rule says never | `denied_by_policy` with the reasons, not retryable |

### Rules only escalate

Start from the tool's tier; each argument rule can move the decision from run to approve, or to deny, never the other way. That makes the policy easy to reason about: adding a rule can't open a hole.

### The approval card

A person can only judge what they can see:

```text
APPROVAL NEEDED  refund  (id c3, expires 14:00)
  user asked : Priya's teapot arrived smashed. Refund her.
  action     : order_id='A-1001', amount=2400
  why        : refund over 100 (2400.0)
  context    : order total 2400.0, item teapot, customer priya@example.com
```

The user's own words, the exact arguments, why it was escalated, and the facts needed to check it. Without the order total, "refund 2400" is impossible to judge.

## Build It

```bash
cd code
python3 main.py
```

```text
c1 lookup_order    -> {"order_id": "A-1001", "email": "priya@example.com", "total": 2400.0, "item": "teapot"}
c2 refund          -> {"refunded": 80, "order_id": "A-1002"}
c3 refund          -> {"status": "waiting_for_approval", "reasons": ["refund over 100 (2400.0)"], ...
c4 refund          -> {"error": "denied_by_policy", "reasons": ["refund 24000.0 is more than the order total 2400.0"], ...
c5 send_email      -> {"sent": true}
c6 send_email      -> {"status": "waiting_for_approval", "reasons": ["email to an address we don't know: 'priya.shah@gmail.com'"], ...
c7 delete_account  -> {"status": "waiting_for_approval", "reasons": ["delete_account always needs approval"], ...
c8 run_sql         -> {"error": "denied_by_policy", "reasons": ["'run_sql' is not an approved tool"], "retryable": false}
```

Then a person approves c3 after checking a photo, rejects c6 ("not the address on the order"), and comes back to c7 five hours later, after it expired.

### Step 1: `evaluate`

The tool's tier, then refund rules (the order must exist, the amount must be a positive number no larger than the order total, over 100 needs approval, a partial refund needs approval) and an email rule (unknown domains need approval). Unknown tools return `deny` before anything else.

### Step 2: `Gate`

`submit` evaluates, logs, and then runs the tool, refuses it, or stores a `Pending` with an expiry (4 hours). `decide` applies a person's decision, checks expiry, and logs who decided. `card` renders the approval card. The clock is injected, so expiry is testable.

### Step 3: The observation for the model

A waiting call returns `{"status": "waiting_for_approval", ..., "note": "Tell the user it is pending; don't call it again."}`. Without that note, a model tends to retry, or tell the user the refund was done.

### Step 4: A real model's calls, through the first policy

```bash
python3 main.py --live --threshold-only     # the policy without the partial-refund rule
```

```text
  refund({"amount": "1", "order_id": "A-1002"}) -> {"refunded": "1", "order_id": "A-1002"}
  refund({"amount": "80", "order_id": "A-1001"}) -> {"refunded": "80", "order_id": "A-1001"}
  send_email({..., "to": "Priya"}) -> {"status": "waiting_for_approval", "reasons": ["email to an address we don't know: 'Priya'"], ...
  delete_account({"email": "tom@example.com"}) -> {"status": "waiting_for_approval", ...
  refund({"order_id": "A-1001", "amount": 5000}) -> {"error": "denied_by_policy", "reasons": ["refund 5000.0 is more than the order total 2400.0"], ...
policy outcomes: {'run': 3, 'approve': 2, 'deny': 1}; effects that happened without a person: ['refund 1 on A-1002', 'refund 80 on A-1001']
```

The policy caught the big mistakes: an email "to" a first name, and a 5,000 "goodwill" refund on a 2,400 order. It missed two small ones:

1. **"Refund him in full"** (an 80 mug) became `refund(amount="1")`, and ran.
2. **Priya's 2,400 teapot** was refunded `"80"`, and ran. 80 is exactly the example value in our own parameter description, `"amount": ("number", "e.g. 80")`, so the model most likely copied it (Exercise 2 tests that). Example values in descriptions help argument *format* (Lesson 6), and they can also be copied as the *value*. Pick examples that are obviously illustrative.

Both were under 100, so the threshold waved them through. Small and wrong is still wrong: one customer got 1 instead of 80, the other 80 instead of 2,400.

### Step 5: Improve the policy from the data

The fix follows from the two mistakes: a refund that isn't the full order total is a *partial* refund, and partial refunds need a person.

```bash
python3 main.py --live
```

```text
  refund({"order_id": "A-1002", "amount": "1"}) -> {"status": "waiting_for_approval", "reasons": ["partial refund: 1.0 of 80.0"], ...
  refund({"amount": "80", "order_id": "A-1001"}) -> {"status": "waiting_for_approval", "reasons": ["partial refund: 80.0 of 2400.0"], ...
policy outcomes: {'run': 1, 'approve': 4, 'deny': 1}; effects that happened without a person: []
```

Nothing wrong happened unsupervised. The cost: four approvals instead of two. That trade-off is the real decision behind every gate, and it should be made with data like this, not guessed.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: unknown tools denied, every refund rule, the partial-refund rule on the two live mistakes (and that the threshold-only policy lets them run), the email rule on the live "Priya", the always-approve tier, nothing pending having happened, the card's contents, approve/reject/expire, and the audit log.

## Use It

| Framework | Approval feature |
|-----------|------------------|
| LangGraph | `interrupt()` in a node; resume with `Command(resume=...)`; the policy is your code before the interrupt |
| Claude Agent SDK / Claude Code | Permission modes and `canUseTool` callbacks: allow, deny, or ask, per tool and arguments |
| OpenAI Agents SDK | Guardrails on inputs and outputs; tool-level checks in your function or a wrapper |
| MCP clients | `destructiveHint` / `readOnlyHint` annotations to decide when to ask the user |

## Ship It

`outputs/skill-approval-policy.md` is a skill that writes an approval policy for an agent's tools (tiers, escalating argument rules, deny-by-default), builds the approval card, and tunes the policy by replaying real model calls and counting what ran unsupervised against how many approvals it costs.

## Exercises

1. **Easy.** Add a rule: refunds on orders older than 30 days are denied. What does the model see?
2. **Medium.** Change the `amount` example in the refund description from `e.g. 80` to `e.g. 12.50`. Re-run `--live --threshold-only`. Does the model still copy the example?
3. **Medium.** Batch approvals: group pending calls by tool and reason, and approve a group at once. When is that safe?
4. **Hard.** Track each approver's approval rate and median decision time. Flag anyone approving 100% in under 5 seconds. What does that tell you about the policy?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Approval policy | "Guardrails" | Rules deciding run / approve / deny for each tool call |
| Tier | "Risk level" | A tool's default outcome |
| Escalating rule | "Condition" | A rule on arguments that can only make the outcome stricter |
| Approval card | "Review screen" | What a person sees to judge a pending call |
| Audit log | "History" | Every decision: what, when, outcome, by whom, why |

## Further Reading

- [LangGraph, Human-in-the-loop](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/)
- [Anthropic, Claude Code: permissions](https://docs.anthropic.com/en/docs/claude-code/iam)
- [Model Context Protocol, Tool annotations](https://modelcontextprotocol.io/docs/concepts/tools#tool-annotations)
- [OWASP, Top 10 for LLM Applications: Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)
