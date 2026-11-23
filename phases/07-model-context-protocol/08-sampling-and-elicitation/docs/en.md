# Sampling and Elicitation

> Sometimes a server needs something only the client side has: an answer from the user, or a completion from the client's model. In the stateless protocol the server doesn't call back. It returns "input required" with a signed note to itself, and the client retries the original request with the answers attached.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 7 · Lessons 3 and 5; Phase 2 · Lesson 8
**Time:** ~45 minutes

## Learning Objectives

- Implement Multi Round-Trip Requests (MRTR): an `input_required` result with `inputRequests` and `requestState`, and a client that fulfils them and retries with `inputResponses`.
- Use elicitation in form mode for missing non-sensitive details and URL mode for anything involving credentials, and handle accept, decline and cancel.
- Explain sampling, why it's deprecated in 2026-07-28, and its migration path.
- Treat `requestState` as attacker-controlled: sign it, bind it to the user, the request and a short expiry, and enforce single use where it matters.

## The Problem

A model calls `book_room(room="Atlas", date="2026-12-03")`. The server needs the number of attendees, which the model didn't send and shouldn't guess. Returning an error makes the model invent a number on its next turn. What the server really wants is to ask the person.

Older revisions handled this by letting the server send its own request back to the client mid-call (`elicitation/create`, `sampling/createMessage`) and wait for the answer. That needs a live, two-way connection pinned to one server instance, holding state while a human reads a form. On a stateless HTTP deployment (Lesson 6), the instance that receives the answer may not be the one that asked.

## The Concept

```
 client                                              server (any instance)
   │ tools/call book_room {room, date}         id 1  │
   │ ─────────────────────────────────────────────►  │  needs attendees
   │ ◄─────────────────────────────────────────────  │
   │   resultType: "input_required"                  │
   │   inputRequests: {details: elicitation/create, form, schema}
   │   requestState: "<signed: user, request digest, expiry, step>"
   │                                                 │
   │  ask the user, get {attendees: 6}               │
   │                                                 │
   │ tools/call book_room {room, date}         id 2  │  verify state, finish
   │   inputResponses: {details: {action: accept, content: {...}}}
   │   requestState: (echoed exactly)                │
   │ ─────────────────────────────────────────────►  │
   │ ◄──────────────── resultType: "complete" ─────  │
```

**Rules.** Only `tools/call`, `prompts/get` and `resources/read` may return `input_required`. The result has `inputRequests`, `requestState` or both. The retry is a new request with a new id. The client echoes `requestState` without reading or changing it. The server never sends an input request type the client didn't declare in `clientCapabilities` (instead it fails with -32021, naming the capability it needed). If an answer is missing or invalid, the server asks again rather than erroring.

**Elicitation** asks the user.

| Mode | For | Shape | Never |
|------|-----|-------|-------|
| `form` | Missing details: counts, choices, dates | `requestedSchema`: a flat object of strings, numbers, booleans, enums | Passwords, tokens, keys, card numbers |
| `url` | Sign-ins, payments, anything sensitive | A URL the client shows in full and opens only with consent | Credentials in the URL itself |

The user's answer is `accept` (with `content` for forms), `decline` (said no) or `cancel` (dismissed it). The client declares which modes it supports: `{"elicitation": {"form": {}, "url": {}}}`.

**Sampling** asks the client's model for a completion (`sampling/createMessage`), so a server can use an LLM without its own API key. It's **deprecated in 2026-07-28** along with Roots and Logging: it still works during the deprecation window, but new servers shouldn't use it. The recommended migration is for the server to call a model provider directly. Two practical problems explain the move: a server borrowing the user's model spends the user's quota on prompts the user didn't write, and every such request needs a human review step in the client to be safe.

**requestState** lets the server be stateless: it puts what it needs to resume (which step, a nonce) into an opaque string and gets it back on the retry. The spec says to treat it as attacker-controlled. If it affects what the server does, the server must protect its integrity (an HMAC or authenticated encryption) and should bind it to the authenticated user, the original request (method plus a digest of the arguments) and a short expiry. A signature doesn't stop the same valid state being submitted twice; operations that must happen at most once need a server-side check.

## Build It

```bash
cd code
python3 main.py
```

The room-booking server and the client run in-process. The "user" filling in forms and the client's "model" answering sampling requests are scripted.

### Step 1: ask for details

```python
return self.ask(principal, req_digest, {"details": {"method": "elicitation/create", "params": {
    "mode": "form",
    "message": f"Booking {args['room']} on {args['date']}. How many people, and do you need a projector?",
    "requestedSchema": {"type": "object", "properties": {
        "attendees": {"type": "integer", "minimum": 1, "maximum": 12, "title": "Attendees"},
        "projector": {"type": "boolean", "title": "Projector", "default": False}},
        "required": ["attendees"]}}}}, {"step": "details", "nonce": secrets.token_hex(8)})
```

The client's loop:

```python
if result["resultType"] == "complete":
    return ...
responses = {k: self.fulfil(req) for k, req in result.get("inputRequests", {}).items()}
params = {"name": name, "arguments": arguments, "inputResponses": responses}
if "requestState" in result:
    params["requestState"] = result["requestState"]
```

```text
1. Elicitation (form): the tool needs details the model didn't have
  id 1 -> input_required: details (elicitation/create)
    user sees form: "Booking Atlas on 2026-12-03. How many people, and do you need a projector?" -> accept {'attendees': 6, 'projector': True}
  -> Booked Atlas on 2026-12-03 for 6 with projector.
```

### Step 2: bad answers and no answers

```text
2. Invalid answer: the server asks again instead of failing
  id 1 -> input_required: details (elicitation/create)
    user sees form: "Booking Atlas on 2026-12-04. How many people, and do you need a projector?" -> accept {'attendees': 40}
  id 2 -> input_required: details (elicitation/create)
    user sees form: "Attendees must be a whole number from 1 to 12." -> accept {'attendees': 9}
  -> Booked Atlas on 2026-12-04 for 9 without projector.

3. The user says no
  decline  -> isError: Not booked: the user declined to give details.
  cancel   -> isError: Not booked: the user dismissed the form.

4. A client that didn't declare elicitation is never sent a form
  -> error -32021: Missing required client capability {'requiredCapabilities': {'elicitation': {'form': {}}}}
```

A decline is a normal outcome, so it's a tool result the model reads ("not booked"), not a protocol error. The client also caps the number of rounds, so a server that keeps asking can't loop forever.

### Step 3: sampling, and what replaces it

```text
5. Sampling (deprecated): the server borrows the client's model, with the user's approval
  id 1 -> input_required: summary (sampling/createMessage)
    user reviews the server's prompt for the client's model -> approve
  -> Summary (scripted-model): Customers like the new search but find checkout slow on mobile.
  without sampling -> isError: Summary unavailable: this client doesn't offer sampling. (The migration path: the server calls its own model provider.)
```

Under MRTR a sampling request travels the same way as a form. The client shows the user what the server wants to send to the model before running it. A server that needs summaries reliably should own its model call; sampling only works with clients that still offer it.

### Step 4: URL mode for sign-ins

```text
6. Elicitation (URL): credentials go to a web page, not through the client
  id 1 -> input_required: link (elicitation/create)
    user sees link https://calendar.example/connect?user=ben (full URL shown) -> accept
  -> Calendar connected.
  cy opens the link but closes the tab, then dismisses the second prompt:
  id 1 -> input_required: link (elicitation/create)
    user sees link https://calendar.example/connect?user=cy (full URL shown) -> accept
  id 2 -> input_required: link (elicitation/create)
    user sees link https://calendar.example/connect?user=cy (full URL shown) -> cancel
  -> isError: Calendar not connected: the user declined.
```

The password goes to the calendar provider's page, never through the MCP client or the model's context. Accepting only means "I opened it"; the retry tells the server to check whether sign-in actually happened, and if not, it asks again.

### Step 5: requestState under attack

```python
if state["sub"] != principal:
    raise RPCError(-32602, "Invalid requestState: issued to another user")
if state["req"] != request_digest:
    raise RPCError(-32602, "Invalid requestState: issued for a different request")
```

```text
7. requestState is attacker-controlled input
  echoed unchanged, same user and request        -> Booked Atlas on 2026-12-07 for 2 without projector.
  the same state sent a second time              -> Already booked with this confirmation; nothing changed.
  edited payload (signature no longer matches)   -> -32602 Invalid requestState: signature
  replayed by another user                       -> -32602 Invalid requestState: issued to another user
  replayed for a different room                  -> -32602 Invalid requestState: issued for a different request
  presented after its 5-minute expiry            -> -32602 Invalid requestState: expired
```

The second row is the one a signature can't catch: the state is genuine. The nonce inside it, checked against a set of used nonces, makes the booking happen once. (Here the set lives in memory; a multi-instance deployment needs it in shared storage, or an idempotency key in the booking system itself, Phase 2 · Lesson 7.)

### Step 6: client-side policy

```text
8. Client policy: forms never collect secrets
    client policy: form asks for ['api_key']; secrets never go through forms -> decline
  -> {'action': 'decline'}
```

The server is the one asking, and servers can be malicious (Lesson 11). The client enforces its own rules no matter what the server's message says.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Situation | Use |
|-----------|-----|
| A tool is missing a detail only the user knows | Form elicitation from inside `tools/call` |
| Connecting a third-party account, payment, sign-in | URL elicitation |
| A server wants an LLM for summarising or classifying | Its own model provider (sampling is deprecated) |
| A dangerous action needs confirmation | The host's own approval gate (Phase 2 · Lesson 8); elicitation is the server asking, approval is the host deciding |
| A client that doesn't support elicitation | Fail with -32021 or an `isError` result that tells the model what's missing |

## Ship It

`outputs/skill-mrtr-elicitation.md` is a skill for adding user input to MCP tools with MRTR: when to elicit versus fail, form versus URL mode, `requestState` design (signed, bound, expiring, single-use where needed), capability checks, client fulfilment rules, and migrating off sampling.

## Exercises

1. **Easy.** Add an `enum` field (`"layout": ["boardroom", "theatre", "u-shape"]`) to the booking form and show it in the scripted user's answer.
2. **Medium.** Use MRTR in `prompts/get`: a `weekly_report` prompt that asks which team the user is on when the `team` argument is missing.
3. **Medium.** Encrypt `requestState` instead of only signing it, so the client can't read the step or nonce. When does that matter?
4. **Hard.** Put two `RoomServer` instances behind a round-robin (Lesson 6) sharing only the signing key. Show the elicitation flow still works when the retry lands on the other instance, and that the double-submit check now needs shared storage.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| MRTR | "Multi round-trip" | A server returns `input_required`; the client retries the original request with the answers |
| `inputRequests` | "What the server needs" | A map of server-chosen keys to elicitation, sampling or roots requests |
| `inputResponses` | "The answers" | The client's results for each key, sent on the retry |
| `requestState` | "Continuation token" | Opaque server data echoed on the retry; attacker-controlled until verified |
| Elicitation | "Ask the user" | A form (non-sensitive fields) or a URL (anything sensitive) the client shows the user |
| Sampling | "Borrow the model" | A server asking the client's model for a completion; deprecated in 2026-07-28 |

## Further Reading

- [MCP specification 2026-07-28: Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)
- [MCP specification 2026-07-28: Elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)
- [MCP specification 2026-07-28: Deprecated features](https://modelcontextprotocol.io/specification/2026-07-28/deprecated)
- [MCP 2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- [Python docs, hmac: compare_digest](https://docs.python.org/3/library/hmac.html#hmac.compare_digest)
