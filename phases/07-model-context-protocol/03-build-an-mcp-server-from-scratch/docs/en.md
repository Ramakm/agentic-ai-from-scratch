# Build an MCP Server from Scratch

> An MCP server is a dispatcher with a contract: tools described by JSON Schema, arguments validated before your code runs, errors split into "tell the model" and "tell the client", and stdout kept clean. Build the small framework once and every server after it is just decorated functions.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 7 · Lesson 2; Phase 2 · Lessons 2, 5 and 6
**Time:** ~60 minutes

## Learning Objectives

- Build a reusable server class: a `@tool` decorator, schemas generated from type hints, and handlers for `server/discover`, `tools/list` and `tools/call`.
- Validate arguments against the input schema before a handler runs, and return problems as a tool result the model can fix.
- Split failures correctly: tool errors (`isError: true`), unexpected crashes (generic message, traceback to stderr), and protocol errors (JSON-RPC `error`).
- Add tool annotations, `structuredContent` with an `outputSchema`, deterministic ordering and cursor pagination.

## The Problem

Lesson 2's server hard-coded two tools inside an `if` chain. A real server has a dozen tools, each with a schema someone has to keep in sync with the code, each needing its arguments checked, each able to fail in a different way. Write that by hand for every tool and three things go wrong:

- **Schema drift.** The function gains a parameter, the hand-written schema doesn't, and the model never learns about it.
- **Unvalidated input.** The model sends `"tags": "it"` instead of `["it"]`, and your code iterates over the characters of a string.
- **Wrong error channel.** A tool fails and the server returns a JSON-RPC error, so the client treats it as a broken connection and the model never sees "no note with that id; search_notes lists ids". Or worse: the server returns the full traceback to the model, file paths and all.

## The Concept

```
 tools/call {name, arguments}
      │
      ├─ _meta missing or bad version ───────────► JSON-RPC error (-32602 / -32022)
      ├─ unknown tool ───────────────────────────► JSON-RPC error (-32602 "Unknown tool")
      ├─ arguments fail the input schema ────────► result, isError: true, list of problems
      ├─ handler raises ToolError ───────────────► result, isError: true, the message
      ├─ handler raises anything else ───────────► result, isError: true, generic message;
      │                                            traceback to stderr
      └─ handler returns ───────────────────────► result, isError: false
                                                   (+ structuredContent if outputSchema)
```

The rule behind the split: **a JSON-RPC error means the request couldn't be processed; a result with `isError: true` means the tool ran (or tried to) and the model should hear about it.** Invalid arguments count as the second kind, because the model can correct them on its next turn (Phase 2 · Lesson 5).

**Tool definition fields.**

| Field | Required | Purpose |
|-------|----------|---------|
| `name` | yes | 1–128 characters of letters, digits, `_`, `-`, `.`; unique within the server |
| `description` | yes in practice | What the model reads to decide when to call it (Phase 2 · Lesson 6) |
| `inputSchema` | yes | A JSON Schema object; a tool with no parameters uses `{"type": "object", "additionalProperties": false}` |
| `title` | no | A human-readable name for UIs |
| `outputSchema` | no | If present, results must include `structuredContent` matching it |
| `annotations` | no | Hints: `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` |

Annotations are **hints from the server, not guarantees**. A host may use them to decide which calls need approval, but a host can't trust them from a server it doesn't trust: a malicious server can mark `delete_everything` as read-only (Lesson 11).

**Listing.** `tools/list` returns tools in a deterministic order (same order every time, so clients can cache and prompts stay stable), with `ttlMs` and `cacheScope` saying how long clients may cache it. Long lists are paginated: the result has `nextCursor`, and the client passes it back as `cursor`. Cursors are opaque to clients.

## Build It

```bash
cd code
python3 main.py
```

`python3 main.py --serve` runs the notes server on stdio; `python3 main.py` spawns it and runs a scripted session.

### Step 1: schema from type hints

```python
def input_schema(fn):
    hints = typing.get_type_hints(fn)
    for name, param in inspect.signature(fn).parameters.items():
        props[name] = schema_for(hints[name])
        if param.default is inspect.Parameter.empty:
            required.append(name)
```

`schema_for` maps `str`, `int`, `float`, `bool`, `list[X]` and `Literal[...]` to JSON Schema, and raises at registration for anything else, so an unsupported type fails when the server starts rather than when the model calls it. Extra constraints (`minLength`, `maximum`) come from the decorator:

```python
@server.tool("Add a note. Returns its id.", title="Add note",
             constraints={"title": {"minLength": 1, "maxLength": 80}})
def add_note(title: str, body: str, tags: list[str] = []) -> str:
```

```text
Schema generated from the type hints of add_note:
  {"type": "object", "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 80}, "body": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}, "default": []}}, "additionalProperties": false, "required": ["title", "body"]}
```

The schema and the function can't drift: one is generated from the other. Official SDKs do the same with type hints (Python) or schema libraries such as Zod (TypeScript).

### Step 2: dispatch and the result envelope

`handle` checks `_meta`, maps `tools/list` to `rpc_tools_list`, and wraps every result with `resultType` and `serverInfo`:

```python
method = getattr(self, "rpc_" + msg["method"].replace("/", "_"), None)
if method is None:
    raise RPCError(-32601, "Method not found", {"method": msg["method"]})
result = {"resultType": "complete", **method(params),
          "_meta": {SERVER_INFO: {"name": self.name, "version": self.version}}}
```

```text
server/discover -> versions ['2026-07-28'], capabilities {'tools': {}}, serverInfo {'name': 'notes', 'version': '1.0.0'}
  instructions: Personal notes. Search before adding to avoid duplicates.

tools/list -> 5 tools (sorted by name)
  add_note      required=['title', 'body'] annotations={}
  delete_note   required=['note_id'] annotations={'destructiveHint': True, 'idempotentHint': True}
  export        required=['fmt'] annotations={'readOnlyHint': True}
  search_notes  required=['query'] annotations={'readOnlyHint': True}
  stats         required=[] annotations={'readOnlyHint': True}
```

`instructions` is optional text a host can add to the model's context: how the server's tools fit together.

### Step 3: validate before the handler runs

```python
problems = validate(args, self.tools[name]["inputSchema"])
if problems:
    return error_result("Invalid arguments: " + "; ".join(problems))
```

```text
  add_note("title": "", "body": "x")
    -> isError: Invalid arguments: arguments.title: length must be >= 1
  search_notes("query": "it", "limit": 50, "sort": "newest")
    -> isError: Invalid arguments: arguments.limit: must be <= 20; arguments: unexpected 'sort'
  add_note("title": "Wifi", "body": "Guest network", "tags": "it")
    -> isError: Invalid arguments: arguments.tags: expected array, got str
```

Every problem is listed at once with its path, so the model can fix them all in one retry. The validator covers the subset the generator produces; a production server uses a full JSON Schema validator.

### Step 4: three kinds of failure

```text
  delete_note("note_id": "n9")
    -> isError: no note with id 'n9'; search_notes lists ids
  export("fmt": "pdf")
    -> isError: Invalid arguments: arguments.fmt: must be one of ['markdown', 'csv']
  export("fmt": "csv")
    -> isError: export failed with an internal error
  drop_all_notes()
    -> protocol error -32602: Unknown tool: drop_all_notes
```

`ToolError` is for failures the model should read and act on, so its message says what to do next. Any other exception is a bug: the model gets a generic message and the traceback goes to stderr, where the operator can see it and the model can't:

```text
Server stderr (tracebacks stay here, not in results):
  [notes] ready
  [notes] export crashed:
    ...
  RuntimeError: csv writer not configured
```

### Step 5: structured output

```python
@server.tool("Count notes and tags.", readOnlyHint=True, output_schema={
    "type": "object", "properties": {"notes": {"type": "integer"}, "tags": {"type": "object"}},
    "required": ["notes", "tags"]})
def stats() -> dict:
```

```text
  stats()
    -> {"notes": 3, "tags": {"finance": 1, "it": 2, "setup": 1}} [+structuredContent]
```

The result carries the dict as `structuredContent` for code (a UI, another tool, a test) and the same data serialised as a text block for models and older clients.

### Step 6: protocol requests and pagination

```text
Protocol-level requests
  tools/list    -> ok
  initialize    -> -32601 Method not found
  prompts/list  -> -32601 Method not found
```

This server implements only the current revision, so the legacy `initialize` handshake is an unknown method; that's exactly the signal a dual-version client uses to tell a modern server from an old one (Lesson 5). Prompts aren't implemented yet (Lesson 4), and the server didn't advertise them in `capabilities`.

```text
Pagination with page_size=2 (in-process)
  pages: [['add_note', 'delete_note'], ['export', 'search_notes'], ['stats']]
```

### Run the tests

```bash
python3 -m unittest -v
```

The tests call `handle` directly for most checks (fast, no subprocess) and run one session over real stdio.

## Use It

| SDK | Equivalent of this lesson |
|-----|---------------------------|
| Python SDK (FastMCP-style API) | `@mcp.tool()` on a typed function; schema from hints, validation via Pydantic |
| TypeScript SDK | `server.registerTool(name, {inputSchema: zodShape}, handler)` |
| Both | `isError` results for tool failures, stdio transport class, pagination helpers |

Once you've built this, an SDK is a better-tested version of the same thing. Reach for one in production; keep this mental model for debugging.

## Ship It

`outputs/skill-mcp-server-scaffold.md` is a skill for building an MCP server: tool registration with generated schemas, validation, the three-way error split, annotations, structured output, deterministic paginated listing, and stdio hygiene, with a checklist to review an existing server against.

## Exercises

1. **Easy.** Add a `rename_note(note_id: str, title: str)` tool. What did you have to write besides the function?
2. **Medium.** Extend `schema_for` to support `int | None` (optional values) and `dict[str, str]`. Add tests.
3. **Medium.** Validate `structuredContent` against `outputSchema` before returning it, and turn a mismatch into an internal error. Why is that a server bug rather than a tool error?
4. **Hard.** Make the server handle requests concurrently (Lesson 2's threading) with a per-tool timeout: a handler that runs longer than its limit returns `isError` with "timed out after N seconds". What happens to the handler thread?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Input schema | "Tool parameters" | A JSON Schema object the server publishes and validates arguments against |
| Tool error | "The tool failed" | A normal result with `isError: true`; the model reads it as an observation |
| Protocol error | "The call failed" | A JSON-RPC `error`; the request couldn't be processed |
| Tool annotations | "Read-only flag" | Server-provided hints about behaviour; untrusted unless the server is |
| `structuredContent` | "JSON output" | Machine-readable result matching `outputSchema`, alongside text content |
| Cursor pagination | "Next page" | `nextCursor` in a list result, passed back as `cursor`; opaque to clients |

## Further Reading

- [MCP specification 2026-07-28: Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [MCP specification 2026-07-28: Pagination](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/pagination)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [JSON Schema reference](https://json-schema.org/understanding-json-schema/reference)
