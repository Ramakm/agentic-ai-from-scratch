# Prompt: Agent Code Review (the four failure points)

Paste this prompt, then the agent code (Python or TypeScript), into any capable model or coding agent.

---

Review this agent code for the four places agent bugs cluster. For each finding, quote the
exact line(s), explain the failure it causes in production, and give the fixed code.

1. **Unvalidated JSON at the boundary.** Is any model output, tool result, or API response
   used without being parsed into a validated type first (dataclass/Pydantic, or a type
   guard/Zod)? Are invalid roles, missing `tool_call_id`s, or wrong types caught where the
   data enters?
2. **Unbounded concurrency.** Are model or tool calls fanned out with `gather` /
   `Promise.all` without a limit (semaphore, worker pool, `p-limit`)? What happens at 100× load?
3. **Missing timeouts.** Can any network call, model call, or tool call wait forever? Is
   a timeout turned into an error *result* the agent can handle, or does it raise through
   the loop?
4. **Non-streamed output.** Does a user-facing path wait for the full model reply when it
   could stream? Is streamed output flushed as it arrives?

Also flag: results mapped back to calls by completion order instead of input order or id,
and retries that hold a concurrency slot while sleeping.

Finish with a table: finding · severity (high/medium/low) · one-line fix.

---

Source: Agentic AI from Scratch, Phase 0, Lesson 2.
