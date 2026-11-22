/* Agentic AI from Scratch — curriculum data.
   Edit SITE to point at your repo; everything else derives from PHASES. */

window.SITE = {
  repo: "Ramakm/agentic-ai-from-scratch",
  maintainer: "Ramakm",
};

/* Each lesson: "Title|minutes". status: complete | in-progress | planned */
window.PHASES = [
  {
    slug: "00-setup-and-tooling", name: "Setup & Tooling", status: "complete",
    desc: "A dev environment, local and hosted models, raw HTTP calls, streaming and tracing, all wired up before writing an agent.",
    lessons: [
      "Your agent dev environment|45", "Python & TypeScript for agents|60", "Running local models with Ollama|40",
      "API keys, providers & rate limits|30", "Calling an LLM over raw HTTP|45", "Streaming responses with SSE|40",
      "Tracing from day one|35", "Project layout for agent repos|30",
    ],
  },
  {
    slug: "01-llm-foundations", name: "LLM Foundations for Agents", status: "complete",
    desc: "What a model actually returns, how context windows fill, and how to force structured, parseable output.",
    lessons: [
      "What an LLM actually returns|45", "Tokens and the context window|50", "Sampling: temperature, top-p, determinism|40",
      "Chat templates and message roles|40", "System prompts as contracts|35", "Structured output & JSON mode|50",
      "Parsing and validating with schemas|45", "Token budgets & cost math|35", "Model selection for agent work|40",
      "Why capable models still fail|45",
    ],
  },
  {
    slug: "02-tool-use", name: "Tool Use & Function Calling", status: "complete",
    desc: "Turn text into action. Tool schemas, dispatchers, parallel calls, and errors fed back as observations.",
    lessons: [
      "Text in, text out: the limit|30", "Tool schemas from first principles|50", "Writing a tool dispatcher|60",
      "Parallel tool calls|45", "Tool errors as observations|40", "Designing tools models can use|50",
      "Idempotency and side effects|40", "Human approval gates|45", "Tool results that fit the context|40",
      "Native function calling across providers|50", "Testing tools in isolation|40",
    ],
  },
  {
    slug: "03-the-agent-loop", name: "The Agent Loop", status: "complete",
    desc: "A while-loop, a model, and a toolbox. ReAct, stop conditions, retries, interrupts, and the loop as a graph.",
    lessons: [
      "The agent loop in 120 lines|60", "ReAct: reason, act, observe|60", "Stop conditions & max steps|35",
      "Scratchpads and thought traces|40", "Handling malformed actions|40", "Retries, backoff & recovery|45",
      "Streaming an agent's steps|45", "Interrupts and resumption|50", "State machines for agents|55",
      "The loop as a graph|55", "Cost and step budgets|35", "Debugging a stuck loop|45",
    ],
  },
  {
    slug: "04-memory-and-context", name: "Memory & Context Engineering", status: "complete",
    desc: "Context is the program. Buffers, summaries, embeddings, a vector store by hand, and memory that stays clean.",
    lessons: [
      "Context is the program|40", "Conversation buffers & truncation|40", "Summarization memory|45",
      "Embeddings from scratch|60", "A vector store in 80 lines|60", "Episodic memory|50",
      "Semantic & procedural memory|50", "Memory writes: what to keep|45", "Context compaction|45",
      "Files as long-term memory|40", "Memory poisoning & hygiene|40",
    ],
  },
  {
    slug: "05-agentic-rag", name: "Retrieval & Agentic RAG", status: "complete",
    desc: "Retrieval as a tool the agent decides to call. Hybrid search, reranking, rewriting, and self-correcting loops.",
    lessons: [
      "Naive RAG and where it breaks|45", "Chunking strategies|45", "Hybrid search: BM25 + vectors|55",
      "Reranking|40", "Query rewriting & decomposition|45", "Retrieval as a tool|45",
      "Self-correcting RAG|55", "Corrective RAG loops|50", "Graph-based retrieval|55",
      "Evaluating retrieval quality|45",
    ],
  },
  {
    slug: "06-planning-and-reasoning", name: "Planning & Reasoning", status: "complete",
    desc: "Plan-and-execute, task trees, Tree of Thoughts, reflection, verifiers, and knowing when not to plan.",
    lessons: [
      "Chain-of-thought for actions|40", "Plan-and-execute|55", "Task decomposition trees|50",
      "Tree of Thoughts search|60", "Reflection & self-critique|45", "Reflexion: learning from failures|55",
      "Verifiers and checkers|50", "Replanning on surprise|45", "Reasoning models in the loop|45",
      "When not to plan|30",
    ],
  },
  {
    slug: "07-model-context-protocol", name: "Model Context Protocol", status: "complete",
    desc: "MCP from the wire up. JSON-RPC over stdio, a server and a client by hand, transports, auth, and security.",
    lessons: [
      "Why MCP exists|35", "The protocol: JSON-RPC over stdio|50", "Build an MCP server from scratch|60",
      "Tools, resources & prompts|50", "Build an MCP client|55", "Streamable HTTP transport|50",
      "Auth for remote servers|50", "Sampling and elicitation|45", "Composing many servers|45",
      "Testing MCP servers|40", "MCP security pitfalls|45",
    ],
  },
  {
    slug: "08-multi-agent-systems", name: "Multi-Agent Systems", status: "complete",
    desc: "Orchestrators, workers, handoffs, supervisors, blackboards, A2A, and the real cost of coordination.",
    lessons: [
      "When one agent is not enough|35", "Orchestrator–worker|55", "Handoffs between agents|50",
      "Supervisor hierarchies|50", "Shared blackboards|45", "Debate and critique|45",
      "Agent-to-agent (A2A) protocol|55", "Message passing & mailboxes|50", "Parallel fan-out, fan-in|45",
      "Role design & specialization|40", "Failure modes of swarms|45", "Cost of coordination|35",
    ],
  },
  {
    slug: "09-frameworks-and-sdks", name: "Frameworks & SDKs", status: "complete",
    desc: "Now import the frameworks. The same loop in LangGraph, Agents SDKs, CrewAI, AutoGen, and when to skip them all.",
    lessons: [
      "The same loop, ten frameworks|40", "LangGraph: state graphs|60", "OpenAI Agents SDK|50",
      "Claude Agent SDK|50", "CrewAI roles & crews|45", "AutoGen conversations|45",
      "LlamaIndex agents|45", "Pydantic AI typed agents|45", "Choosing (or skipping) a framework|35",
      "Porting between frameworks|45",
    ],
  },
  {
    slug: "10-coding-and-computer-use", name: "Coding & Computer-Use Agents", status: "complete",
    desc: "Agents that edit files, run tests, drive browsers and terminals. Ends with a mini coding agent of your own.",
    lessons: [
      "Anatomy of a coding agent|45", "File read, edit & search tools|55", "Running code in a sandbox|55",
      "Test-driven agent loops|55", "Repository maps & context|50", "Skills and SKILL.md|45",
      "Browser agents|55", "Computer use: screenshots to clicks|60", "Terminal agents|50",
      "Long-horizon tasks|50", "Build a mini coding agent|90",
    ],
  },
  {
    slug: "11-evaluation-and-observability", name: "Evaluation & Observability", status: "complete",
    desc: "Golden tasks, trajectory evals, careful LLM judges, OpenTelemetry traces, replay, and your own eval harness.",
    lessons: [
      "Why agent evals are hard|35", "Golden tasks & datasets|45", "Trajectory evaluation|50",
      "LLM-as-judge, carefully|50", "Tool-call accuracy|40", "Tracing with OpenTelemetry|50",
      "Replay and regression|45", "Online metrics & feedback|40", "Benchmarks: SWE-bench to τ-bench|45",
      "Building an eval harness|70",
    ],
  },
  {
    slug: "12-safety-and-security", name: "Safety, Security & Guardrails", status: "in-progress",
    desc: "The agent threat model. Prompt injection, exfiltration, least privilege, sandboxes, permissions, red-teaming.",
    lessons: [
      "The agent threat model|45", "Prompt injection, direct & indirect|55", "Data exfiltration paths|45",
      "Least-privilege tools|40", "Sandboxing with containers|55", "Permission systems|50",
      "Input & output guardrails|45", "Secrets and credentials|35", "Human-in-the-loop design|40",
      "Red-teaming your agent|55", "Audit logs|35",
    ],
  },
  {
    slug: "13-production-agents", name: "Production Agents", status: "in-progress",
    desc: "Durable execution, queues, caching, routing, cost control, versioning, and incident playbooks.",
    lessons: [
      "From notebook to service|45", "Durable execution|55", "Queues, workers & long jobs|50",
      "Prompt caching & latency|45", "Cost control at scale|40", "Model routing & fallbacks|45",
      "Versioning prompts and tools|40", "Deploying with Docker|45", "Rate limits & backpressure|40",
      "Incident playbooks|35",
    ],
  },
  {
    slug: "14-agent-ux", name: "Agent UX & Interfaces", status: "planned",
    desc: "Streaming step views, approvals and undo, voice, background agents, and the design of trust.",
    lessons: [
      "Streaming UIs for agents|45", "Showing the work: step views|40", "Approvals & undo|40",
      "Chat is not the only interface|35", "Voice agents|55", "Background agents & notifications|40",
      "Generative UI|45", "Trust and explainability|35",
    ],
  },
  {
    slug: "15-capstone-agent-harness", name: "Capstone: Your Own Agent Harness", status: "planned",
    desc: "Everything at once. A loop, tool registry, memory, MCP, subagents, permissions, and evals, shipped as a CLI.",
    lessons: [
      "Why build a harness|35", "The core loop & tool registry|70", "Memory & context manager|70",
      "MCP client integration|60", "Subagents & delegation|60", "Permissions & sandbox|60",
      "Evals & traces|60", "Ship it: CLI + docs|60",
    ],
  },
];
