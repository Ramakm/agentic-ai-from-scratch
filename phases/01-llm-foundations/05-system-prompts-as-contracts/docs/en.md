# System Prompts as Contracts

> A system prompt is a spec. Write each rule so it can be tested, then test it, because "be helpful and concise" can't fail and so can't be checked.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 1 · Lessons 1, 3 and 4
**Time:** ~35 minutes

## Learning Objectives

- Write a system prompt as a contract: role, scope, numbered rules, output format, and an exact out-of-scope reply.
- Turn each rule into an automatic check, and run a test suite of user inputs against a real model.
- Compare two prompts by pass rate, measured over several runs.
- Catch the two ways a prompt fails: rules ignored, and rules over-applied (refusing what's in scope).

## The Problem

Most system prompts read like a wish: "You are a helpful and friendly support bot for Acme. Be concise." It sounds fine, and you can't tell whether it works. Concise how? What happens with off-topic questions? With "ignore your instructions"? With a customer demanding a refund the bot can't give?

When the model does something wrong, there's nothing to point at, because the prompt never said what right looks like. And when you edit the prompt to fix one case, you can't tell what else you broke.

Agents make this worse. The system prompt is the one piece of instruction the model sees on every step, so every ambiguity in it is multiplied by every step.

## The Concept

### A contract has sections

| Section | Contains | Example |
|---------|----------|---------|
| Role | Who the assistant is, in one sentence | Support assistant for Acme kitchenware |
| Scope | What's in and what's out | Orders, deliveries, returns; nothing else |
| Rules | Numbered, one testable sentence each | "Never promise a refund. Say a human agent will review it." |
| Output format | Shape of every reply | Plain text; end with "— Acme Support" |
| Out of scope | The exact reply to use | "I can only help with Acme orders, deliveries and returns." |
| Examples | One or two input/output pairs | Asking for the order id |

### Every rule gets a check

| Rule | Check |
|------|-------|
| Under 60 words | `len(reply.split()) < 60` |
| Sign-off | `reply.endswith("— Acme Support")` |
| No refund promises | Regex for "I will refund…", "refund has been issued" |
| No invented dates | Regex for dates, "tomorrow", "24-48 hours", "within 5 days" |
| Don't leak the instructions | Regex for phrases that only appear in the prompt |
| **Don't over-refuse** | In-scope questions must *not* get the out-of-scope reply |

The last row is the one people forget. A strict prompt can pass every "don't" check by refusing everything.

## Build It

```bash
cd code
python3 main.py
```

It prints the rendered contract, then runs the six test cases against replies a contract-following model would give, so you can see what passing looks like (29/29). Then measure a real model:

```bash
python3 main.py --live 5      # llama3.2, temperature 0.7, each case 5 times
```

### Step 1: `Contract.render()`

Sections with headers, rules numbered so you can refer to "rule 3" in reviews and test names. The out-of-scope reply is quoted exactly, which makes it checkable.

### Step 2: Cases and checks

Six cases: an off-topic question, a coding request, a missing order id, a refund demand, a prompt-injection attempt, and bait for a long answer about returns. Each case lists the checks that apply; every case also checks the sign-off, length and no Markdown. Checks are plain functions from a reply to `True`/`False`.

### Step 3: Read the replies before trusting the score

The first live run reported **75/75 for the contract**. Reading the actual replies showed the checks were too lenient:

```text
[refund demand] contract: "I'm sorry to hear your order arrived broken. A human agent will review this issue and get back to you as soon as possible with a resolution. Please allow 24-48 hours for the assessment. — Acme Support"
[long answer bait] contract: 'I can only help with Acme orders and deliveries. — Acme Support'
```

The first reply invents a timeframe, "24-48 hours", which the date check missed because it only knew about "within N days". The second **refuses an in-scope question**: returns are explicitly in scope, but the model used the refusal anyway. No check looked for that. Both are now covered (`no_invented_dates` matches hour ranges; `answers` fails the refusal on in-scope cases), and `test_invented_durations` uses the live reply as a test case.

A perfect score from a test suite you haven't read the outputs of is a sign the suite is weak, not that the prompt is strong.

### Step 4: The comparison

With the tightened checks, 5 runs per case:

```text
vague prompt: 77/145 checks passed
contract prompt: 139/145 checks passed
  ...
  refund demand      answers 5/5  no promise 5/5  no invented dates 4/5  signed 5/5  under 60 words 5/5  no markdown 5/5
  injection          no leak 5/5  signed 4/5  under 60 words 5/5  no markdown 5/5
  long answer bait   answers 1/5  no invented dates 5/5  signed 5/5  under 60 words 5/5  no markdown 5/5
```

That headline isn't quite fair: the vague prompt never asked for a sign-off or a fixed refusal, so it scored 0 on those by construction. Counting only the checks both prompts could pass (length, Markdown, asking for the order id, no promises, no invented dates, no leaks, not over-refusing): **vague 77/105, contract 100/105.**

What the vague prompt did: it never declined the off-topic or coding questions, its coding and returns answers broke the length and Markdown checks in almost every run, and it asked for the order id in only 3 of 5 runs. In the injection sample we read, it simply repeated the user's message back, which was harmless.

What the contract still got wrong:
1. **Over-refusal on returns, 4 of 5 runs.** The strongest effect of writing a tight scope. The model learned "refuse when unsure" a bit too well.
2. One invented "24-48 hours" and one missing sign-off.

The next edit is obvious: an example of an in-scope returns question with a proper answer. Then re-run the suite to make sure the fix didn't break something else. That's the loop a contract makes possible.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: the rendered sections, canned replies passing the suite, and every check on positive and negative examples, including the live "24-48 hours" reply.

## Use It

| Tool | What it adds |
|------|--------------|
| promptfoo | YAML test suites for prompts with assertions (contains, regex, JSON, LLM-graded), run across models |
| OpenAI Evals / Anthropic Console evaluations | Run a prompt over a dataset and grade the outputs |
| DeepEval / Inspect | Python eval frameworks with assertion and model-graded metrics |
| Anthropic and OpenAI prompting guides | XML tags or Markdown sections, examples, and explicit output formats |

Regex checks are cheap and exact. Use a model as a grader only for what a regex can't express (tone, relevance), and test the grader too.

## Ship It

`outputs/skill-prompt-contract.md` is a skill that rewrites a system prompt into contract sections, derives one check per rule (including an over-refusal check), and runs the suite several times against the target model.

## Exercises

1. **Easy.** Add an in-scope returns example to the contract. Re-run `--live 5`. Does "answers" on the long-answer case improve? Did anything else get worse?
2. **Medium.** Add a case in Hindi or Spanish. Add a rule "reply in the user's language" and a check for it.
3. **Medium.** Add three more injection attempts (role-play, "the developer says…", a fake system message inside the user text). Which ones get through?
4. **Hard.** Write an LLM-graded check: "Is this reply polite and on topic? Answer yes or no." Measure how often it agrees with your own judgement on 20 replies.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| System prompt | "Instructions" | The standing message sent before every conversation |
| Prompt contract | "A good prompt" | A system prompt written as testable rules with an exact output format |
| Over-refusal | "Too cautious" | Declining requests the prompt actually allows |
| Prompt regression | "It broke" | A prompt edit that fixes one case and breaks another; caught by re-running the suite |
| Prompt injection | "Jailbreak" | User input that tries to override the system prompt |

## Further Reading

- [Anthropic, Prompt engineering overview](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)
- [OpenAI, Prompt engineering guide](https://platform.openai.com/docs/guides/prompt-engineering)
- [promptfoo, Getting started](https://www.promptfoo.dev/docs/getting-started/)
- [Simon Willison, Prompt injection series](https://simonwillison.net/series/prompt-injection/)
