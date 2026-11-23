# When One Agent Is Not Enough

> Split an agent when you can name the pressure: too many tools to choose between, more context than one window holds, independent work that could run in parallel, or parts that need different permissions. Splitting without one of those just adds calls, handoffs and new ways to fail.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lessons 1 and 11; Phase 4 · Lesson 1; Phase 2 · Lesson 6
**Time:** ~35 minutes

## Learning Objectives

- Measure tool-choice errors for one agent with 24 tools versus a router plus domain specialists, and see what each design gets wrong.
- Compute peak context and total tokens read when independent work shares one window versus separate windows.
- Name the four pressures that justify more than one agent, and the cheaper fixes to try first.
- Write a decision rule that returns "one agent" or "multi-agent" with reasons.

## The Problem

Multi-agent systems are easy to draw: a planner box, three worker boxes, arrows. They're expensive to run and hard to debug, because every arrow is a model call, a context handoff and a place for information to get lost (Phase 8 · Lessons 11 and 12). Most tasks that seem to need a team are handled better by one agent with good tools.

But some aren't. An agent given every tool in the company picks the wrong `search`. An agent researching three vendors drags all three vendors' pages through every later call until the window overflows. An agent that reads untrusted email shouldn't hold the payment tool. The question isn't "would more agents be cool?" but "which of these pressures do I have, and is splitting the cheapest fix?"

## The Concept

| Pressure | Symptom | Try first | Split when |
|----------|---------|-----------|------------|
| Tool overload | Wrong tool among similar ones; long tool lists in every call | Better tool names and descriptions (Phase 2 · Lesson 6); select tools per task (Phase 7 · Lesson 9) | Tools fall into clear domains with their own vocabulary |
| Context overload | Early results crowd out later work; window overflow | Summarise or compress results (Phase 4) | The work splits into independent parts that each fit a window |
| Parallelism | Long sequential runs of independent work | Parallel tool calls in one agent (Phase 2 · Lesson 4) | Each part needs its own multi-step loop |
| Separation of trust | Untrusted input and dangerous tools in one context | Approval gates (Phase 2 · Lesson 8) | One part must never be steerable by another's input (Phase 12) |

Every split adds a **routing or delegation step that can itself be wrong**, more model calls, and a handoff where details get lost. A router is a new classifier with its own error rate; the overall chance of getting the right tool is roughly the router's accuracy times the specialist's.

## Build It

```bash
cd code
python3 main.py
```

The tool picker here is a stand-in: it chooses the option whose name and description share the most words with the request, with ties going to the first option. It confuses similar tools for the same reason models do (overlapping names and descriptions), but its numbers describe this toy, not any real model. `--live` asks a real model to pick instead.

### Step 1: 24 tools, four of them called `search`

Four domains (docs, tickets, CRM, calendar), six tools each, with the same verbs in every domain: `search`, `get`, `create`, `update`. 24 requests, each with the right answer.

### Step 2: one agent versus a router

```python
def single_agent(request, pick):
    options = all_tools()
    return pick(request, options), 1, tokens(options)

def routed(request, pick, domain_text=DOMAINS):
    domains = {d: f"Handles {desc}." for d, desc in domain_text.items()}
    domain = pick(request, domains)
    tools = {f"{domain}.{t}": desc for t, desc in TOOLS.get(domain, {}).items()}
    return pick(request, tools), 2, tokens(domains) + tokens(tools)
```

```text
Tool choice with 24 tools (word-overlap stand-in)
  one agent, all tools                     19/24 right, 24 calls, ~335 tokens of options per request
  router (vague domains) + specialist      15/24 right, 48 calls, ~153 tokens of options per request
  router (specific domains) + specialist   20/24 right, 48 calls, ~194 tokens of options per request
```

Splitting with vague domain descriptions made things **worse**: the router sent five requests to the wrong specialist, and no specialist can recover from that. With domain descriptions in the words requests actually use (ids like `INC-311`, verbs like "report a bug"), routing fixed the cross-domain confusion and beat one agent by one request, at twice the calls.

### Step 3: read the misses

```text
  one agent misses:
    'Open document DOC-88': picked docs.search, wanted docs.get
    'Fix a typo in the travel policy document': picked docs.search, wanted docs.update
    'Which incidents are still open?': picked tickets.create, wanted tickets.list_open
    'Show event EVT-3': picked calendar.search, wanted calendar.get
    'Set up a meeting with Ana and Ben on Friday': picked crm.log_call, wanted calendar.create
```

```text
  specific router misses:
    'Open document DOC-88': picked docs.search, wanted docs.get
    'Fix a typo in the travel policy document': picked docs.search, wanted docs.update
    'Which incidents are still open?': picked docs.search, wanted tickets.list_open
    'Show event EVT-3': picked calendar.search, wanted calendar.get
```

Only one of the single agent's misses crossed domains ("set up a meeting" went to the CRM's `log_call`). The rest are `get` versus `search` inside one domain: a tool-description problem that splitting can't fix. "Get a document by its id" never says "open". Improve the descriptions and both designs improve, for no extra calls.

### Step 4: context pressure

Three independent research threads produce tool results of a few thousand tokens each.

```text
Context: three research threads (16000-token window)
  one agent holds every result:   peak 31100 tokens (over the window)
  worker 'pricing':       peak 10100 tokens
  worker 'security':      peak 9100 tokens
  worker 'integrations':  peak 11900 tokens
  lead agent reads 3 summaries:   1200 tokens
  tokens read over all model calls: one agent 166600, split 71600
  (each call re-reads its own context; workers never re-read each other's results)
```

Each model call re-reads the whole context, so one agent pays for pricing pages again while it's researching integrations. Separate windows avoid that, and the lead only reads three 400-token summaries. Don't over-read the total: in practice, teams of agents do more work than one agent (more searches, more checking). Anthropic reported its multi-agent research system used about 15 times the tokens of a chat, against about 4 times for a single agent. The split saves tokens per unit of work and then usually does more work.

### Step 5: the decision

```python
def assess(t, tool_limit=12, window=WINDOW):
    if t["separate_permissions"]: ...   # isolate
    if t["independent_parts"] > 1 and t["context_tokens"] > window: ...   # orchestrator-worker
    if t["tools"] > tool_limit: ...     # route to specialists, or select tools per task
    if t["context_tokens"] > window and t["independent_parts"] == 1: ...  # compress, don't split
```

```text
Decisions
  Answer a question about the expense policy
    -> one agent: fits one agent: small tool set, one window
  Triage a support inbox using tickets, docs and CRM (24 tools)
    -> multi-agent: 24 tools > 12: route to specialists (or select tools per task)
  Research 3 vendors on pricing, security and integrations
    -> multi-agent: 3 independent parts and 34000 tokens > 16000 window: orchestrator-worker
  Read untrusted emails and also send payments
    -> multi-agent: parts need different trust levels: isolate them (reader without side-effect tools)
  Refactor one function and run its tests
    -> one agent: fits one agent: small tool set, one window
```

The thresholds (12 tools, a 16,000-token window) are placeholders. Set yours from your own traces: the tool count where choice errors start to climb, and your model's effective window.

### Run the tests

```bash
python3 -m unittest -v
```

### Try a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

The live run makes 72 model calls (24 single-agent picks and 48 routed ones). Compare which requests a real model confuses with the stand-in's misses.

## Use It

| Pattern | Addresses | Lesson |
|---------|-----------|--------|
| Orchestrator–worker | Context overload, parallel independent work | 8.2 |
| Handoffs | Tool overload by domain; a conversation moving between specialists | 8.3 |
| Supervisor hierarchies | Many specialists, too many for one router | 8.4 |
| Shared blackboard | Specialists contributing to one evolving picture | 8.5 |
| Debate and critique | Checking work with a second, independent context | 8.6 |
| Reader / actor split | Separation of trust | Phase 12 |

## Ship It

`outputs/skill-should-i-split-my-agent.md` is a skill that decides whether an agent should become several: it measures tool-choice errors and context growth from traces, tries the single-agent fixes first, names the pressure and the pattern if splitting is justified, and estimates the extra calls.

## Exercises

1. **Easy.** Rewrite the four `get` descriptions to mention "open" and "show". How many misses disappear for each design?
2. **Medium.** Add a fifth domain (`hr`) with the same four verbs. Plot one-agent accuracy as the tool count grows from 6 to 30.
3. **Medium.** Change `tokens_read` so the lead agent makes three calls (plan, check, write) and each worker re-reads a 2,000-token shared background. Where is the break-even?
4. **Hard.** Run `--live` with a small and a large model. Does the router help the small model more than the large one? Explain why with the misses.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Tool overload | "Too many tools" | Choice errors and context cost that grow with the number of similar tools |
| Context overload | "Context rot" | Earlier material crowding out or confusing later work in one window |
| Router | "Triage agent" | A step that picks which specialist handles a request; its errors can't be recovered downstream |
| Specialist | "Sub-agent" | An agent with a narrow tool set and instructions for one domain |
| Separation of trust | "Isolation" | Keeping untrusted input away from contexts that hold dangerous tools |

## Further Reading

- [Anthropic, How we built our multi-agent research system (2025)](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Anthropic, Building effective agents (2024)](https://www.anthropic.com/engineering/building-effective-agents)
- [Cognition, Don't Build Multi-Agents (2025)](https://cognition.ai/blog/dont-build-multi-agents)
- [Cemri et al., Why Do Multi-Agent LLM Systems Fail? (2025)](https://arxiv.org/abs/2503.13657)
- [OpenAI, A practical guide to building agents (2025)](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)
