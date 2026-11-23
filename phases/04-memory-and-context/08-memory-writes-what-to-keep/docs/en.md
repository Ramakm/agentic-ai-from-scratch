# Memory Writes: What to Keep

> Let the model propose memories, and let code decide. Every write must quote what the user actually said, and pass gates for secrets, durability, specificity, consent and duplicates.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 4 · Lesson 7; Phase 1 · Lesson 7
**Time:** ~45 minutes

## Learning Objectives

- Explain why "store everything the model extracts" fills memory with guesses, moods, secrets and duplicates.
- Implement a write policy as ordered gates: grounded, not secret, durable, specific, consented, not a duplicate.
- Require every candidate memory to carry the user's exact quote, and reject candidates whose quote the user never wrote.
- Score a write policy against a human reviewer's labels, including the cases it gets wrong.

## The Problem

Lessons 6 and 7 built stores. Something has to decide what goes into them. The obvious design is to ask the model after each turn: "extract anything worth remembering about the user". It will happily oblige. From one short conversation it proposes:

- that she is exhausted (true today, irrelevant next week);
- her card number (she gave it for one order; storing it is a security and compliance problem);
- that she has type 2 diabetes (health data: she shared it for this request, not necessarily for ever);
- that her income is "high" (she never said anything about income);
- that she "likes stuff" (nothing to act on);
- that she is allergic to nickel (already stored).

Each of these will come back in every future prompt (Lesson 1). A wrong memory is worse than no memory: the agent will act on it with confidence, and the user can't see why.

## The Concept

### Propose, then decide

| Step | Who | Why |
|------|-----|-----|
| Propose candidates | The model | Good at noticing what might matter in free text |
| Decide each candidate | Plain code (a write policy) | Rules must be predictable, testable and auditable |
| Write | The store (Lesson 7) | Supersede rules and history |

### The gates, in order

| Gate | Rejects | How |
|------|---------|-----|
| **Grounded** | Inferences and inventions | The candidate's `quote` must appear in what the user wrote |
| **Not secret** | Card numbers, API keys, passwords | Patterns; checked on quote and value |
| **Durable** | Moods, "today", "right now" | Time words; or a `kind` the extractor sets |
| **Specific** | "likes stuff" | Vague-value list, minimum length |
| **Consented** | Health, religion, politics, salary... | Ask the user first; store only with consent |
| **Not a duplicate** | Facts already stored | Compare with the store; same value is a skip, different value is an update |

Order matters. A secret must be rejected even if it is also a duplicate. An ungrounded claim must never reach the consent question ("Shall I remember that your income is high?").

A rate limit on top caps writes per turn, so a broken extractor can't flood memory.

### Grounding checks the quote, not the leap

Requiring an exact quote stops pure invention: "income: high" has no quote, and is rejected. It doesn't stop over-interpretation. "We're moving to Pune" is a real quote; "has a partner" is a leap from it. The policy stores it. A human reviewer would not. You'll see this in the score.

## Build It

```bash
cd code
python3 main.py
```

```text
keep everything the extractor proposes:
  12 writes, including a card number, a mood, a diagnosis, and a guess about income

with the write policy:
  skip    name          'Priya'                     duplicate: already stored
  update  diet          'vegan'                     changes 'vegetarian'
  store   dairy         'avoids dairy'              new, grounded, durable, specific
  reject  mood          'exhausted'                 transient: true now, not next week
  skip    allergy       'nickel'                    duplicate: already stored
  ask     health        'type 2 diabetes'           sensitive: ask the user before storing
  store   dessert       'prefers low-sugar desser'  new, grounded, durable, specific
  reject  payment_card  '4111 1111 1111 1111'       secret: never store credentials or card numbers
  reject  likes         'stuff'                     vague: nothing specific to act on later
  store   city          'Pune (from June)'          new, grounded, durable, specific
  reject  income        'high'                      not grounded: the quote is not in what the user said
  store   family        'has a partner'             new, grounded, durable, specific  (reviewer: reject)

score against a human reviewer: {'agree': '11/12', 'stored': 5, 'wrongly_stored': 1}
```

The twelve candidates are what an eager extractor might return; each is labelled with what a careful human reviewer would decide. The policy agrees on 11. The one miss is "has a partner", for the reason above. Keep a miss like that in your test set; it reminds everyone what the gates don't cover.

### Step 1: `Candidate` carries its quote

The extractor must return `quote`: the user's exact words. That single field makes the most important gate cheap. It also makes memory explainable later: "I remembered that because you said 'I'm vegan now'".

### Step 2: `decide()`

Each gate is two or three lines, and the first failing gate returns a `Decision` with an action and a reason. `normalise()` lowercases and collapses whitespace before the grounding check, so a quote that differs only in case or spacing still counts.

The patterns are deliberately simple. The card pattern catches 16-digit numbers in groups; the key pattern catches `sk-` keys; the transient pattern catches a handful of time words. Production systems use proper secret scanners and a classifier for durability, but keep the same shape: a list of gates, each one testable on its own.

### Step 3: `ask` is a real outcome

Sensitive attributes are not rejected. They return `ask`. Your agent then asks: "Would you like me to remember that for future orders?" If the user says yes, call `decide()` again with that attribute in `consented`. Several privacy laws (the GDPR among them) treat health data as a special category; consent before storing it is the safe default.

### Step 4: `apply()` and the rate limit

Writes only `store` and `update` decisions, at most `max_writes` per turn, and marks the rest `skip` with the reason "rate limit".

### Step 5: A real extractor

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

The model gets `EXTRACT_PROMPT` and the seven user messages, and must return a JSON list. `parse_candidates()` is lenient about text around the list and strict about keys; unparseable output produces no writes, never a crash. Then the same policy decides. Look at how many candidates come back with quotes the user never wrote; models often paraphrase in the `quote` field even when told to copy. Should paraphrased quotes be rejected? That is a real trade-off (Exercise 2).

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eleven tests: each gate, case-insensitive grounding, consent, duplicates and updates, apply, the rate limit, the lesson's score (including the miss), and lenient-but-strict parsing.

## Use It

| System | How it decides what to store |
|--------|------------------------------|
| ChatGPT memory | The model decides; users can see, edit and delete memories, and turn memory off |
| Mem0 | An LLM extracts facts, then chooses ADD, UPDATE, DELETE or NONE against existing memories |
| LangMem | Memory managers that extract and consolidate memories, with schemas you define |
| Letta (MemGPT) | The agent edits its own memory blocks through tools |

Most frameworks let the model decide end to end. If you use one, you can still put your own gates between the extraction and the write.

## Ship It

`outputs/skill-memory-write-policy.md` is a skill that adds a write policy to an agent's memory: quote-carrying candidates, ordered gates, an `ask` path for sensitive data, a rate limit, a decision log, and a labelled test set scored against a human reviewer.

## Exercises

1. **Easy.** Add a gate that rejects candidates about other people ("my boss hates meetings") unless they are about how to help the user. What should `subject` be for those?
2. **Medium.** Accept paraphrased quotes when at least 80% of the quote's words appear in one user message. Which candidates change decision? Which new failures does it allow?
3. **Medium.** Add a second model call as a gate: "Does this quote directly support this value? Answer yes or no." Does it catch "has a partner"? What does it cost per turn?
4. **Hard.** Build a labelled set of 50 candidates from real conversations (with permission) or from your own. Measure how many wrong writes your policy lets through and how many good writes it blocks. Which gate makes the most mistakes?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Write policy | "Memory rules" | Code that decides, for each proposed memory, whether to store, update, skip, reject or ask |
| Grounding | "Based on what they said" | The candidate quotes the user's exact words, and the quote is checked |
| Transient fact | "Temporary" | True at the moment ("tired today") and useless or wrong later |
| Consent | "Opt-in" | The user agrees before sensitive information is stored |
| Over-interpretation | "Reading into it" | A real quote, and a value that goes beyond what it says |

## Further Reading

- [Chhikara et al., Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory (2025)](https://arxiv.org/abs/2504.19413)
- [OpenAI, Memory and new controls for ChatGPT](https://openai.com/index/memory-and-new-controls-for-chatgpt/)
- [GDPR Article 9: processing of special categories of personal data](https://gdpr-info.eu/art-9-gdpr/)
- [LangMem, Memory management concepts](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)
