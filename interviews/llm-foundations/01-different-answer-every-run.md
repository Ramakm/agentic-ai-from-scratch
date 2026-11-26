# The agent takes a different path every run, even at temperature 0

> Your agent sets `temperature=0`. A user reports that the same request sometimes calls `search` first and sometimes calls `lookup_order` first, and once it skipped a step entirely. A teammate says "temperature 0 means deterministic, so it must be a bug in our code." What do you tell them, and what do you do about it?

**Level:** 1
**Type:** Concept
**Time:** ~6 minutes
**Taught in:** 01-llm-foundations/03-sampling-temperature-top-p-determinism, 01-llm-foundations/01-what-an-llm-actually-returns

## Short answer

Temperature 0 means greedy decoding: always pick the most likely next token. It doesn't make the whole system deterministic. Hosted inference batches your request with others, and floating-point sums on GPUs depend on batch shape and kernel choice, so two near-tied tokens can swap. One different token early in a tool call changes everything after it. Providers document seeds as best effort. So design for variation: make the agent correct on any valid path, test with several runs per case, and pin behaviour that must be fixed in code, not in sampling settings.

## Full answer

### What temperature actually controls

The model returns a probability distribution over the next token. Temperature rescales it before sampling; at 0 you take the argmax. That removes *sampling* randomness, not *numerical* randomness.

### Where the variation comes from

| Source | Why it changes the output |
|--------|---------------------------|
| Batching on the server | Different batch sizes change the order of floating-point additions; results differ in the last bits |
| Near-tied tokens | When two tokens are almost equally likely, those last bits decide which wins |
| Mixture-of-experts routing | Token routing can depend on what else is in the batch |
| Model and prompt updates | A silent model snapshot change or an edited system prompt moves everything |
| Your own context | Timestamps, retrieved documents in a different order, tool results that vary |

One flipped token in the first tool call sends the trajectory down a different branch. Agents amplify small differences because every step conditions on the previous ones.

### What to do

- **Accept several valid paths.** "Look up the order, then check policy" and the reverse are both fine. Evaluate with rules about what matters (Phase 11 trajectory specs), not exact sequences.
- **Run each eval case more than once** and report the pass rate, not a single pass/fail.
- **Put hard requirements in code.** If `lookup_order` must come before `issue_refund`, enforce it in the tool or dispatcher.
- **Remove your own nondeterminism.** Stable ordering of retrieved docs, no timestamps in prompts unless needed, pinned model versions.
- **Log the full request** so a strange run can be replayed (Phase 11 · Replay and regression).

## Follow-ups

- **L2.** The provider offers a `seed` parameter. Does that fix it? *Expected:* It reduces variation, but providers describe it as best effort and expose a fingerprint that changes when the backend changes. Don't build correctness on it.
- **L2.** Should you just use temperature 0 everywhere in an agent? *Expected:* Often a low temperature for tool selection is sensible, but some tasks (brainstorming, retries after failure) benefit from diversity. Correctness should not depend on the setting either way.
- **L3.** How would you test that the agent is robust to this variation? *Expected:* Run each golden task N times, report pass@k and pass^k (all k runs pass), and look at the spread, not the best run.

## Wrong answers

- "Temperature 0 is deterministic, so this is a bug in our code." Greedy decoding on batched GPU inference isn't bit-for-bit reproducible, and providers don't promise it.
- "Set the seed and the problem is solved." Seeds are best effort and break when the serving stack changes.
- "Add 'always do the steps in this order' to the prompt." That lowers the rate but guarantees nothing. Ordering that matters belongs in code.
