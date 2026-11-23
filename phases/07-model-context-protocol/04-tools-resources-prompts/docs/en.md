# Tools, Resources & Prompts

> A server offers three kinds of thing, and the difference is who decides when they're used. The model calls tools. The application attaches resources. The user picks prompts. Put a capability in the wrong bucket and either the model can't reach it or it reaches things it shouldn't.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 7 · Lesson 3; Phase 4 · Lesson 1
**Time:** ~50 minutes

## Learning Objectives

- Implement resources (`resources/list`, `resources/read`, `resources/templates/list`) with text and binary contents and URI templates.
- Serve files from a folder through a resource template without path traversal, including encoded `..` and symlinks.
- Implement prompts (`prompts/list`, `prompts/get`) with required and optional arguments, embedding resources in the messages.
- Link tools to resources with `resource_link` results, and cache list and read results by `ttlMs`.

## The Problem

Lesson 3's server had only tools. Everything a model could get from it, it had to ask for with a tool call. That's wrong for two kinds of content:

- **Context the application already knows it needs.** An IDE knows which file is open; a support app knows which ticket the agent is working on. Making the model call `read_file` first costs a turn and might not happen at all. The application should just attach it.
- **Workflows the user starts on purpose.** "Summarize this policy for new joiners" or "check this expense" are tasks someone runs by name, with arguments, the same way every time. Hiding them in a tool means the model has to guess when to use them.

There's also a safety side. Anything exposed as a tool is something the model can call whenever it decides to, including after reading a prompt injection (Phase 12 · Lesson 2). Data a model never needs to fetch on its own shouldn't be a tool.

## The Concept

| | Tools | Resources | Prompts |
|---|---|---|---|
| Controlled by | The model | The application | The user |
| Typical UI | Invisible, or an approval dialog | A file picker, "attach", automatic context | Slash commands, a menu |
| Discover | `tools/list` | `resources/list`, `resources/templates/list` | `prompts/list` |
| Use | `tools/call` {name, arguments} | `resources/read` {uri} | `prompts/get` {name, arguments} |
| Returns | Content blocks, `isError`, maybe `structuredContent` | `contents`: text or base64 `blob`, each with `uri` and `mimeType` | `messages` ready to add to the conversation |
| Side effects | Allowed | None (reads) | None (builds messages) |

**Resources** are identified by URIs: `handbook://policies/expenses`, `file:///forms/leave.txt`. The scheme is the server's choice. Servers list concrete resources, and can also publish **URI templates** (RFC 6570) like `handbook://policies/{name}` for families of resources too large or dynamic to list. A missing resource is error -32602 with the URI in `data`.

**Prompts** take named string arguments, some required. `prompts/get` returns messages, which can contain text or **embedded resources** (the resource's contents inside the message), so a prompt can bring its own context with it.

**Links between them.** A tool result can contain `resource_link` blocks pointing at resources. The model gets a short answer plus pointers, and the host (or the model, via another call) reads only what's needed (Phase 2 · Lesson 9).

**Caching.** List and read results carry `ttlMs` (how long a client may reuse it) and `cacheScope` (`public`: same for every user; `private`: this user's data, don't share across users).

## Build It

```bash
cd code
python3 main.py
```

The handbook server runs in-process (`server.handle(method, params)`); the transport is Lesson 2's and adds nothing new here.

### Step 1: list and read resources

```text
Resources (the application decides what to attach)
  handbook://it/vpn                text/markdown
  handbook://policies/expenses     text/markdown
  handbook://policies/travel       text/markdown
  handbook://assets/logo.png       image/png
  template handbook://policies/{name}  Policy by name
  template file:///{+path}             File in the shared handbook folder
  read handbook://policies/travel -> Book economy for flights under 6 hours.
  read logo.png -> blob, 33 bytes, starts b'\x89PNG'
  template handbook://policies/{name} matches handbook://policies/travel: {'name': 'travel'}
```

Text goes in `text`; binary goes base64-encoded in `blob`. Templates match with a small regex: `{name}` matches one path segment, `{+path}` matches across slashes (RFC 6570's reserved expansion).

### Step 2: serve a folder safely

`file:///{+path}` serves files from a shared folder. Next to that folder sits `payroll.csv`, and inside it a symlink `forms/summary.txt` points at payroll.

```python
full = os.path.realpath(os.path.join(self.files_root, path))
if os.path.commonpath([full, self.files_root]) != self.files_root:
    raise RPCError(-32602, "Resource not found", {"uri": uri})
```

```text
Sandboxed files behind file:///{+path}
  file:///forms/leave.txt                      -> Leave request form: name, dates, manager.
  file:///../payroll.csv                       -> -32602 Resource not found
  file:///forms/%2e%2e/%2e%2e/payroll.csv      -> -32602 Resource not found
  file:///forms/summary.txt                    -> -32602 Resource not found
  file:///forms/missing.txt                    -> -32602 Resource not found
```

Three attacks, one check. The URI is percent-decoded first, so `%2e%2e` becomes `..`. `realpath` resolves `..` and follows symlinks, so the check sees where the file really is. `commonpath` compares whole path components (a string `startswith` check would let `/srv/shared-evil` pass for `/srv/shared`). Every refusal looks the same as "missing", so a caller can't probe what exists outside the folder.

### Step 3: prompts with arguments

```text
Prompts (the user picks one, like a slash command)
  /summarize_policy(policy, audience?)  Summarize one handbook policy for an audience.
  /check_expense(amount_eur, category)  Check an expense against the expense policy.
  /summarize_policy policy=expenses ->
    user: [embedded handbook://policies/expenses, 96 chars]
    user: Summarize the policy above for new joiners in three bullet points.
  /check_expense {'amount_eur': '55'} -> -32602 Missing required arguments {'missing': ['category']}
  /summarize_policy {'policy': 'parking'} -> -32602 Unknown policy: parking
```

The host shows `/summarize_policy` in its command menu, asks the user for `policy`, calls `prompts/get`, and appends the returned messages to the conversation. The prompt embeds the policy text itself, so the model has the context without a tool call. Missing required arguments are -32602, listing which.

### Step 4: tools that point at resources

```text
Tools (the model decides when to call)
  search_handbook: Search the handbook. Returns links to matching pages; read them for details.
  search_handbook('receipts hotel') -> ['1 page(s) match.', 'link handbook://policies/expenses']
  search_handbook('parking') -> ['No pages match.']
```

```python
links = [{"type": "resource_link", "uri": u, "name": ..., "title": t, "mimeType": "text/markdown"} ...]
return {"content": [{"type": "text", "text": f"{len(links)} page(s) match."}, *links], "isError": False}
```

The search stays small. Reading a linked page is a separate `resources/read`, which the host can do directly or show to the user.

### Step 5: cache by `ttlMs`

```text
Caching by ttlMs (page ttlMs=60000, list ttlMs=300000)
  t=  0s resources/read  miss (sent to server)
  t= 30s resources/read  hit
  t= 61s resources/read  miss (sent to server)
  t= 61s resources/list  miss (sent to server)
  t=200s resources/list  hit
  t=362s resources/list  miss (sent to server)
```

The client stores each result with an expiry of `now + ttlMs`. The page read is `cacheScope: "private"`, so a host serving several users keys it per user; the lists are `public`.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Host behaviour | Primitive |
|----------------|-----------|
| "@-mention" or attach a file, issue or doc to the conversation | Resource read by the application |
| A slash-command menu populated from connected servers | Prompts |
| An approval dialog before an action runs | Tool call |
| A model asking for a page it found in search results | `resource_link` followed by a read |

Host support varies: tools are universal, resources and prompts less so. If your server's main value is a resource, also offer a read-only tool that returns it, so hosts that only support tools can still reach it.

## Ship It

`outputs/skill-mcp-primitive-design.md` is a skill for deciding which capabilities of a server become tools, resources or prompts, designing URIs and templates, sandboxing file-backed resources, writing prompt arguments, and setting `ttlMs`/`cacheScope`.

## Exercises

1. **Easy.** Add a `handbook://policies/{name}` read path so any policy can be read through the template, not only listed pages. What should happen for `handbook://policies/../it/vpn`?
2. **Medium.** Add a `holidays` prompt with an optional `year` argument that embeds a resource only when the year is known. What should `prompts/get` do with an argument that isn't declared?
3. **Medium.** Make the cache respect `cacheScope`: key private results by user id, and show two users never share one.
4. **Hard.** Paginate `resources/list` for a folder with 10,000 files using a cursor that encodes the last path returned rather than an offset. Why is that more robust when files are added between pages?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Resource | "Context" | Read-only data identified by a URI, attached by the application |
| URI template | "Dynamic resource" | An RFC 6570 pattern like `handbook://policies/{name}` describing a family of resources |
| Prompt | "Slash command" | A user-selected template with arguments that returns ready-made messages |
| Embedded resource | "Inline context" | A resource's contents placed inside a prompt message |
| `resource_link` | "Link in a result" | A tool result block pointing at a resource URI instead of including its contents |
| Path traversal | "../ attack" | Escaping a served folder with `..`, encoded `..`, absolute paths or symlinks |

## Further Reading

- [MCP specification 2026-07-28: Resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)
- [MCP specification 2026-07-28: Prompts](https://modelcontextprotocol.io/specification/2026-07-28/server/prompts)
- [RFC 6570: URI Template](https://datatracker.ietf.org/doc/html/rfc6570)
- [OWASP, Path Traversal](https://owasp.org/www-community/attacks/Path_Traversal)
- [Python docs, os.path.realpath and commonpath](https://docs.python.org/3/library/os.path.html)
