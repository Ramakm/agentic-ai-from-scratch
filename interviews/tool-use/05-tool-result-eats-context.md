# One tool result ate the context window

> Your agent calls `list_tickets()` and gets 3,000 tickets back as JSON: 400,000 tokens. The call fails with a context-length error, or, on a big-context model, succeeds but the answer is slow, expensive and wrong. How should tools return data to a model?

**Level:** 2
**Type:** Design
**Time:** ~8 minutes
**Taught in:** 02-tool-use/09-tool-results-that-fit-the-context, 04-memory-and-context/01-context-is-the-program

## Short answer

Design results for a reader with a small, expensive working memory. Filter and paginate at the source (`list_tickets(status, since, limit=20)` with a cursor), return only the fields the model needs, and include counts so it knows what it isn't seeing ("showing 20 of 3,000; use `page`"). For big payloads, store the full result and return a handle plus a summary, so the model can query or pass it to code without reading it. Enforce a size cap in the dispatcher as a backstop.

## Full answer

### Techniques

| Technique | Example |
|-----------|---------|
| Filter in the tool | Required filters (`status`, `since`), sensible defaults |
| Paginate | `limit` + `cursor`, and say there's more |
| Project fields | `id, title, status, updated_at` instead of 60 fields |
| Summarise | "3,000 tickets: 2,400 closed, 450 open, 150 pending" |
| Handles | `result_id: r-17` stored server-side; tools like `query_result(r-17, filter)` |
| Hard cap | Dispatcher truncates anything over N tokens and says so |

### Tell the model what it's not seeing

Truncation without a note makes the model believe it has everything. Always include totals and how to get more.

### Let code do the heavy lifting

If the question is "how many open tickets per team?", give a tool that computes it, or a sandboxed code tool over the stored result. Don't make the model count 3,000 items in its context.

## Follow-ups

- **L2.** Big-context models can take the 400k tokens. Why not just do that? *Expected:* Cost and latency every subsequent turn (it stays in history), and accuracy drops on retrieval and counting across very long inputs.
- **L3.** How do you choose the cap? *Expected:* From the context budget per turn and measurements of answer quality vs result size; log when truncation happens so tools can be improved.
- **L3.** What about errors and stack traces? *Expected:* Same idea: return the relevant lines and a summary, not a 2,000-line trace.

## Wrong answers

- "Use a model with a bigger window." It costs more on every later turn and still degrades on huge inputs.
- "Truncate to the first N characters." Silent truncation hides data and can cut JSON mid-object.
- "Let the model ask for less next time." It can't know there was more if the tool doesn't say so.
