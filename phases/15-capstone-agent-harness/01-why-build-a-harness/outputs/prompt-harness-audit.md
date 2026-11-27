# Prompt: audit an agent harness

Use this with any capable model to audit an agent setup: your own harness, a framework, or a vendor's agent. Paste the prompt, then the code, config or docs you have.

---

You are reviewing an AI agent harness: the code around a model's tool-calling loop. For each of the seven situations below, find what this harness actually does, citing the file, function, config key or documentation section. If you can't find evidence, say "not found". Don't assume a feature exists because similar products have it.

1. **Broken tool arguments.** The model sends invalid JSON, a missing argument, or the wrong type. Does the run crash, or does the model get an error it can act on?
2. **Unknown tools.** The model calls a tool that doesn't exist. What happens? How are third-party tools (e.g. MCP servers) added, namespaced and isolated?
3. **Runaway loops.** The model repeats the same call, or never stops. Which limits exist: steps, tokens or cost, repeated calls, wall time? Are they shared with subagents?
4. **Context growth.** A tool returns a huge result, or the task runs for 100 steps. Is output clipped? Is history compacted? Can a compaction leave a tool result without its call?
5. **Delegation.** Can work be handed to a subagent with a fresh context? What can a subagent do that its parent can't, and what can't it do?
6. **Side effects.** Which tool calls run without a human? How are rules expressed? How are compound shell commands and command substitution handled? What environment do shell commands and MCP servers inherit?
7. **False success.** The model says "done, tests pass." Does anything check that independently? Are there traces and evals that would catch a regression?

Output:

| # | Situation | What it does (with evidence) | Gap | Severity (high/medium/low) |
|---|-----------|------------------------------|-----|----------------------------|

Then list the three gaps to fix first, each with a one-sentence reason. Severity is high if a gap can cause data loss, leaked secrets, or a false report of success.
