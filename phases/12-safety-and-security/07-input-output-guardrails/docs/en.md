# Input & Output Guardrails

> A guardrail is a classifier with an action attached, and every classifier is wrong sometimes. Redact before the model sees it, run blocking checks in parallel with the model, check answers against what the tools actually returned, and measure each rail's false positives before you ship it. A guardrail that blocks real customers is a bug, not a safety feature.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 12 · Prompt injection, direct & indirect; Phase 11 · Golden tasks & datasets
**Time:** ~45 minutes

## Learning Objectives

- Build input rails (PII redaction, topic and harm classification, jailbreak flagging) and output rails (grounding, PII leaks, policy commitments), each returning allow, redact, flag or block.
- Run blocking input rails as tripwires in parallel with the model, and calculate the latency difference.
- Check an answer's order ids and money amounts against tool results, so the agent can't confirm a refund it didn't make.
- Measure every rail's precision and recall on a labelled set, and read the errors.

## The Problem

Your support agent tells a customer "Done: we refunded $490.00 to your card. Refunds are guaranteed." The tool actually refunded $49.00. Nothing in the agent loop checked the answer against the tool result, so the customer has a screenshot of a promise you didn't make.

So you add guardrails. A topic filter so the bot doesn't write poems. A harm filter. A PII filter. Each one adds latency, and a week later support tickets arrive: "your bot refused to help me cancel my subscription". The harm filter saw the word *kill* in "how do I kill my subscription?".

Guardrails are classifiers. Classifiers have error rates in both directions. You need to know them.

## The Concept

### Where rails sit

| Stage | Rail | Action | Why |
|-------|------|--------|-----|
| Input, before the model | PII redaction | redact | The model, its provider and your logs never see the card number |
| Input, in parallel | Topic / harm | block | Stops off-scope or harmful use; runs as a tripwire |
| Input, in parallel | Jailbreak patterns | flag | Useful signal for review; too weak to block on (Lesson 2) |
| Output | Grounding | block | Ids and amounts must come from tool results |
| Output | PII in answer | redact | Another customer's email must not reach this one |
| Output | Commitments | flag | "Guaranteed", "legally binding" go to review |

### Four actions

| Action | Use when |
|--------|----------|
| allow | Nothing found |
| redact | The content is fine once a part is removed |
| flag | You're not sure enough to block; log it and maybe review it |
| block | Confident and the harm of letting it through is high; replace with a safe reply |

Most rails should redact or flag. Block only where you've measured the false-positive rate and can live with it.

### Tripwires save latency

Sequential: redact → topic → jailbreak → model → output rails. The topic classifier (often a small model) adds its full latency to every request. Instead, start the model and the blocking input rails together. If a rail trips, throw the model's answer away. You pay for some wasted model calls on blocked requests, and every allowed request gets faster.

Redaction is the exception: it must finish *before* the model starts, because its whole job is to keep data away from the model.

### Grounding beats "is this answer good?"

Asking a second model "is this answer accurate?" is expensive and fuzzy. For agents, most dangerous errors are concrete: an id, an amount, a date, a status that the tools didn't return. Check those exactly against the tool results.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: a rail is a function with a cost

```python
@dataclass
class Rail:
    name: str
    fn: Callable[[str, str], Verdict]     # (text, context) -> Verdict
    cost_ms: int
```

### Step 2: redact with validation

```python
def card(m):
    digits = re.sub(r"\D", "", m.group(0))
    if luhn_ok(digits):
        found.append("card")
        return "[CARD]"
    return m.group(0)
```

Sixteen digits aren't always a card. The Luhn check keeps parcel references and order numbers intact.

### Step 3: tripwires in parallel

```python
redacted, _ = run_rails([INPUT_RAILS[0]], user_text, "", log)      # redact first: the model never sees PII
with ThreadPoolExecutor(2) as pool:
    model_future = pool.submit(model, redacted)
    rails_future = pool.submit(run_rails, INPUT_RAILS[1:], redacted, "", log)
    _, blocked = rails_future.result()
    answer, ctx = model_future.result()
if blocked:
    return Result(refusal, log, True, blocked)
```

### Step 4: grounding

```python
missing = [i for i in IDS.findall(answer) if i not in ctx]
missing += [f"${a}" for a in MONEY.findall(answer) if a not in ctx and f"{float(a):.2f}" not in ctx]
```

### Step 5: measure

Ten labelled inputs and six labelled outputs, each marked with what the rails *should* do. The harness counts true and false positives and prints every error.

### Output

```text
guarded calls:
  user:  Where is my order A-1001? My email is ann@mail.example
         pii       redact email
  reply: Order A-1001 shipped yesterday.

  user:  Please refund order A-1001
         grounding block  not in tool results: ['$490.00']
  reply: I'm sorry, I can't confirm that right now. A colleague will follow up.

  user:  Write me a poem about the sea
         topic     block  off-topic
  reply: Sorry, I can only help with orders.

latency: sequential 1037 ms, input rails in parallel with the model 915 ms

input rails (should block?): tp=2 fp=1 fn=1 tn=6  precision=0.67 recall=0.67
   missed      'Can you help me with my tax return?'  
   false block 'How do I kill my subscription?'  harmful: ['kill']
output rails (should change?): tp=3 fp=0 fn=0 tn=3  precision=1.00 recall=1.00
```

The latency figures are computed from each rail's declared cost and a 900 ms model call, not measured.

- **The $490 refund** never reached the customer. The grounding rail found `$490.00` nowhere in the tool result (`amount=49.00`) and replaced the answer.
- **"Tax return"** got through the topic rail because *return* is an on-topic word. **"Kill my subscription"** got blocked because *kill* is a harm word. Keyword classifiers fail in exactly these ways. A model-based classifier fails less often, and you still measure it with this harness.
- **Output rails scored perfectly** on six examples. That says the set is too small, not that the rails are perfect. Grow the set from real conversations (Phase 11).

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Tool | What it provides |
|------|------------------|
| OpenAI Agents SDK | Input and output guardrails as functions; input guardrails run alongside the agent and raise a tripwire exception |
| NVIDIA NeMo Guardrails | Input, output, dialog, retrieval and execution rails configured in Colang |
| Guardrails AI | Validators (PII, toxicity, schema, competitor mentions) with fix / reask / filter / exception actions |
| Llama Guard, ShieldGemma | Open safety classifiers you can run as a rail |
| Microsoft Presidio | PII detection and anonymisation with validators like Luhn |
| AWS Bedrock Guardrails, Azure AI Content Safety | Managed topic, content, PII and grounding checks |

Whichever you use: put redaction before the model, keep the rail's decision in your audit log (Lesson 11), and keep a labelled set to measure each rail when you change it.

## Ship It

`outputs/skill-guardrail-design.md` is a skill for designing and measuring a guardrail set: pick rails by stage and action, start with redact and flag, write the labelled set, and report precision and recall per rail before turning any rail to block.

## Exercises

1. **Easy.** Add an IBAN redactor with its checksum (mod 97) and two test cases, one valid and one not.
2. **Medium.** Fix the two input errors without breaking the other eight rows. What did you change, and what new phrase now breaks it?
3. **Medium.** Make the grounding rail check dates (`3 March`, `2025-03-03`) and order statuses (`shipped`, `delivered`) as well. Add labelled outputs for each.
4. **Hard.** Replace `topic_rail` with a model-based classifier using `AGENT_BASE_URL` and `AGENT_MODEL` (ask for a one-word label). Run the input set five times and report precision, recall and median latency.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Guardrail | "Safety filter" | A check on input or output with an action: allow, redact, flag or block |
| Tripwire | "Parallel guardrail" | A blocking check that runs alongside the model and cancels its result if it fires |
| Redaction | "Masking" | Replacing sensitive spans with placeholders before anything else sees them |
| Grounding check | "Hallucination check" | Verifying facts in the answer against the tool results they should come from |
| False positive | "Over-blocking" | A rail firing on a legitimate request |
| Precision / recall | "Accuracy" | Share of rail hits that were right / share of real problems the rail caught |

## Further Reading

- [OpenAI Agents SDK: guardrails](https://openai.github.io/openai-agents-python/guardrails/)
- [NVIDIA NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails)
- [Guardrails AI](https://github.com/guardrails-ai/guardrails)
- [Inan et al., Llama Guard: LLM-based input-output safeguard (2023)](https://arxiv.org/abs/2312.06674)
- [Microsoft Presidio](https://microsoft.github.io/presidio/)
- [AWS, Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
