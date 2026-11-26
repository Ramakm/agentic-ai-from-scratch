# Forty tools, and the model keeps picking the wrong one

> Your agent started with 6 tools and worked well. Teams kept adding tools; now there are 40, including `search_docs`, `search_kb`, `find_article` and `lookup_help`. Tool-selection accuracy dropped and token costs rose. How do you fix it?

**Level:** 2
**Type:** Design
**Time:** ~10 minutes
**Taught in:** 02-tool-use/06-designing-tools-models-can-use, 11-evaluation-and-observability/05-tool-call-accuracy

## Short answer

Treat the toolset as an interface designed for the model. Merge overlapping tools so each job has one obvious tool, give names and descriptions that say when to use each one (and when not to), and keep parameters few and typed. Then reduce what each call sees: group tools by domain and load only the relevant group, or give the model a tool-search tool. Measure tool-call accuracy on a labelled set before and after, because "it feels better" isn't a result.

## Full answer

### Why more tools hurt

Every definition is in every prompt (cost and latency), and similar tools force the model to guess between near-synonyms. Accuracy drops most where descriptions overlap.

### Design fixes

| Problem | Fix |
|---------|-----|
| Four search tools | One `search(query, source)` with an enum, or keep separate tools with sharply different descriptions |
| Vague descriptions | Say what it returns, when to use it, and when to use another tool instead |
| Many optional parameters | Split by use case or set defaults in code |
| Low-level CRUD tools | Expose task-level tools (`refund_order`) instead of `update_row` |
| Similar names across teams | Namespaces: `billing_…`, `crm_…` |

### Show fewer tools per call

- **Routing:** classify the request, then load that domain's tools.
- **Tool search:** a `find_tools(query)` tool returns relevant definitions on demand.
- **Sub-agents:** a billing agent with billing tools, called by an orchestrator.

### Measure

Build 50–200 labelled requests with the expected tool and arguments. Track accuracy, confusion between specific tool pairs, and argument errors. The confusion matrix shows exactly which descriptions to rewrite.

## Follow-ups

- **L2.** What makes a good tool description? *Expected:* What it does, what it returns, when to use it, when not to, constraints on arguments, one example if ambiguous. Written for the model, not for the API docs.
- **L3.** Routing adds a classifier step. When is that worth it? *Expected:* When tool count or token cost is high and domains are separable; measure end-to-end accuracy and latency, since routing errors cascade.
- **L3.** Who should own tool quality across teams? *Expected:* A review process or registry with naming rules, description standards and the accuracy eval in CI, so a new tool can't silently degrade selection.

## Wrong answers

- "Use a bigger model." It helps a little; overlapping, vague tools confuse every model.
- "Put a long list of 'use X for Y' rules in the system prompt." That's a description problem; fix the descriptions and merge the duplicates.
- "Add more examples of each tool." Examples cost tokens on every call and don't fix overlap.
