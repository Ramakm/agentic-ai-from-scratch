# Agent-to-Agent (A2A) Protocol

> MCP connects an agent to tools. A2A connects an agent to another agent it doesn't control: built by another team or company, running elsewhere, with its own model and data. You see its card, send it messages, and track a task through states until it hands back artifacts. What happens inside stays inside.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 7 · Lessons 2 and 6; Phase 8 · Lesson 2
**Time:** ~55 minutes

## Learning Objectives

- Publish and read an A2A v1.0 Agent Card at `/.well-known/agent-card.json`: interfaces, capabilities and skills.
- Implement the JSON-RPC binding's core methods (`SendMessage`, `GetTask`, `CancelTask`, `SendStreamingMessage`) for a remote agent.
- Drive a task through its states, including `TASK_STATE_INPUT_REQUIRED` for multi-turn exchanges, and read artifacts made of text and data parts.
- Choose between waiting, polling and streaming for long tasks, and handle A2A errors.

## The Problem

Everything in this phase so far has been agents you wrote, in one process, sharing your code and your model. Real organisations don't look like that. The travel team has a booking agent; the finance team has an expense agent; a partner company offers a logistics agent. Your agent wants to delegate to them, but it can't import their code, doesn't know which model they use, and shouldn't see their prompts or internal data.

You could wrap each one as an MCP tool, and for a simple request and response that works. But an agent isn't a function. A booking can take minutes, needs to ask a follow-up question ("what's your budget?"), produces documents rather than one return value, and might be cancelled halfway. That needs a protocol built around tasks and conversations between peers: A2A.

## The Concept

```
 your agent (client)                                  hotel agent (remote, opaque)
   │ GET /.well-known/agent-card.json  ─────────────►  name, skills, interfaces, capabilities
   │ SendMessage {message}             ─────────────►  creates task
   │ ◄──── {task: state INPUT_REQUIRED, status.message: "max price per night?"}
   │ SendMessage {message with taskId, data part}  ─►  same task continues
   │ ◄──── {task: state COMPLETED, artifacts: [text part, data part]}
```

| | MCP | A2A |
|---|---|---|
| Connects | An agent (host) to tools, resources and prompts | An agent to another agent |
| The other side is | A capability provider you call | A peer with its own reasoning, model and state |
| Unit of work | A tool call that returns a result | A task with a lifecycle and artifacts |
| Multi-turn | `input_required` round trips (Phase 7 · Lesson 8) | `TASK_STATE_INPUT_REQUIRED` and follow-up messages on the same task |
| Discovery | `server/discover`, `tools/list` | The Agent Card |

They compose: a remote A2A agent probably uses MCP servers internally, and your host might expose "delegate to the hotel agent" to its model as a tool.

**Core objects in v1.0.**

| Object | Fields that matter |
|--------|-------------------|
| Agent Card | `name`, `description`, `version`, `provider`, `supportedInterfaces[{url, protocolBinding, protocolVersion}]`, `capabilities{streaming, pushNotifications}`, `defaultInputModes`, `defaultOutputModes`, `skills[{id, name, description, tags, examples}]` |
| Message | `messageId`, `role` (`ROLE_USER` or `ROLE_AGENT`), `parts`, optional `taskId` and `contextId` |
| Part | One of `text`, `data` (JSON), `url` (a file reference) or `raw` (base64 bytes), plus optional `mediaType` and `filename` |
| Task | `id`, `contextId`, `status{state, message, timestamp}`, `artifacts`, `history` |
| Artifact | `artifactId`, `name`, `parts`: the task's output |

**Task states.** `TASK_STATE_SUBMITTED` and `TASK_STATE_WORKING` while running. `TASK_STATE_INPUT_REQUIRED` and `TASK_STATE_AUTH_REQUIRED` mean the task is paused, waiting for the client. `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, `TASK_STATE_CANCELED` and `TASK_STATE_REJECTED` are terminal: no more messages.

**Versions.** v1.0 (March 2026) renamed methods to `SendMessage`-style names, made enum values `SCREAMING_SNAKE_CASE`, and dropped the `kind` field from parts. Older v0.3 code uses `message/send`, `"completed"` and `{"kind": "text"}`. A card can list interfaces for both versions while clients migrate. Requests carry an `A2A-Version` header.

## Build It

```bash
cd code
python3 main.py
```

Both agents run on localhost. The remote hotel agent is scripted, standing in for whatever model or system sits behind a real A2A endpoint. A client never sees it anyway.

### Step 1: the card

```python
"supportedInterfaces": [{"url": base + "/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
"capabilities": {"streaming": True, "pushNotifications": False},
"skills": [{"id": "book-hotel", "name": "Book a hotel", "description": ..., "tags": ["travel", "hotel", "booking"],
            "examples": ["Book a hotel in Lisbon from Dec 3 to Dec 5 under 150 EUR a night"]}],
```

```text
1. Discovery: GET /.well-known/agent-card.json
   Hotel Booking Agent v2.1.0 by Example Travel
   interface: JSONRPC 1.0 at <base>/a2a; streaming=True
   skills: [('book-hotel', ['travel', 'hotel', 'booking'])]
```

The client picks the interface whose binding and version it speaks, and uses the skills' descriptions, tags and examples the way a host uses tool descriptions: to decide whether this agent fits the job.

### Step 2: a multi-turn task

```python
task = client.call("SendMessage", {"message": user_message("Book a hotel in Lisbon from Dec 3 to Dec 5")})["task"]
...
reply = user_message(data={"max_per_night": 150}, task=task)   # sets taskId and contextId
task = client.call("SendMessage", {"message": reply})["task"]
```

```text
2. SendMessage, then the agent needs more input
   task c23ccf6e: TASK_STATE_INPUT_REQUIRED - What's your maximum price per night, in EUR?
   (same taskId, data part {'max_per_night': 150})
   task c23ccf6e: TASK_STATE_COMPLETED
   artifact 'booking': Booked Casa Azul, 128 EUR/night, 2 nights.
   artifact 'booking': {"hotel": "Casa Azul", "city": "Lisbon", "nightly_eur": 128, "nights": 2, "confirmation": "HB-C23CCF"}
```

The answer went back as a `data` part, structured JSON rather than prose, so the remote agent doesn't have to parse "about a hundred and fifty". The artifact has both: a text part for a person, a data part for code.

### Step 3: long tasks, three ways

By default `SendMessage` waits until the task finishes or pauses. With `configuration.returnImmediately`, it returns at once and the client polls:

```text
3. returnImmediately, then poll GetTask
   states seen: TASK_STATE_WORKING -> TASK_STATE_COMPLETED; result: Booked Alfama Rooms, 96 EUR/night, 2 nights.
```

Or the client streams, if the card says `streaming: true`:

```text
4. SendStreamingMessage: events as they happen
   statusUpdate: TASK_STATE_WORKING - Searching Lisbon hotels under 200 EUR
   artifactUpdate: Booked Hotel Tejo, 172 EUR/night, 2 nights.
   statusUpdate: TASK_STATE_COMPLETED
```

Each SSE event's `result` holds one of `task`, `message`, `statusUpdate` or `artifactUpdate`. For tasks that take hours, A2A also defines push notifications to a client webhook, which this server doesn't offer (`pushNotifications: false`).

### Step 4: cancel and errors

```text
5. CancelTask while it's working
   TASK_STATE_CANCELED - Cancelled before booking; nothing was reserved.

6. Errors
   GetTask with an unknown id         -> -32001 Task not found (TASK_NOT_FOUND)
   CancelTask on a completed task     -> -32002 Task cannot be canceled (TASK_NOT_CANCELABLE)
   a method this agent doesn't have   -> -32601 Method not found (METHOD_NOT_FOUND)
   a request outside its skills       -> TASK_STATE_REJECTED - I can only book hotels in cities I know: Lisbon
```

Errors carry a `google.rpc.ErrorInfo` entry in `data` with a machine-readable `reason`. Check your SDK's error table for the exact codes; the reason strings are the stable part. Note the last row: "I can't do that" isn't a protocol error. The request was fine, and the agent declined the task.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Tool | Role |
|------|------|
| A2A SDKs (Python, JavaScript, Java, Go, .NET) | Server and client classes for all three bindings (JSON-RPC, gRPC, HTTP+JSON) |
| Agent frameworks (Google ADK and others) | Expose an agent over A2A, or call a remote A2A agent as a sub-agent |
| A2A Inspector / TCK | Inspect a live agent; check conformance |
| Agent Card signing | JWS signatures on cards, so clients can verify who published them |

Security carries over from Phase 7: authenticate both directions (`securitySchemes` on the card), treat artifacts and status messages as untrusted input (Phase 7 · Lesson 11), and give delegated tasks only the data they need.

## Ship It

`outputs/skill-a2a-integration.md` is a skill for exposing or calling an agent over A2A: writing an honest card, choosing input and output modes, task state transitions, multi-turn input, polling vs streaming vs push, cancellation, errors, versions, and the security review.

## Exercises

1. **Easy.** Add a second skill, `cancel-booking`, to the card and implement it. How does a client decide which skill a message is for, given that `SendMessage` doesn't name one?
2. **Medium.** Make the client an LLM tool: `delegate_to_hotel_agent(request)` returns the artifact text, or the agent's question when the task needs input. What should happen to the `taskId` between the model's turns?
3. **Medium.** Implement `ListTasks` filtered by `contextId`, and use `contextId` to group three related bookings into one trip.
4. **Hard.** Serve v0.3 and v1.0 side by side: a second interface in the card with `protocolVersion: "0.3"`, accepting `message/send` and returning `"completed"` and `{"kind": "text"}` parts. Write a client that prefers 1.0 and falls back.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| A2A | "Agent-to-agent" | An open protocol (Linux Foundation project) for agents to discover and delegate to each other |
| Agent Card | "Agent manifest" | JSON at `/.well-known/agent-card.json` describing an agent's skills, interfaces and auth |
| Task | "Job" | A unit of work with an id, states, history and artifacts |
| Artifact | "Output" | What a task produced, made of text, data or file parts |
| Opaque agent | "Black box" | The remote agent's prompts, model and tools are never exposed to the client |
| Context | "Conversation id" | `contextId` grouping related tasks and messages |

## Further Reading

- [A2A Protocol specification](https://a2a-protocol.org/latest/specification/)
- [What's new in A2A v1.0](https://github.com/a2aproject/A2A/blob/main/docs/whats-new-v1.md)
- [A2A on GitHub](https://github.com/a2aproject/A2A)
- [A2A and MCP](https://a2a-protocol.org/latest/topics/a2a-and-mcp/)
- [RFC 8615: Well-Known URIs](https://datatracker.ietf.org/doc/html/rfc8615)
