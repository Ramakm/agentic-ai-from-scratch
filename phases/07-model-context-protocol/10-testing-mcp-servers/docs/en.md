# Testing MCP Servers

> Unit tests check that your tools compute the right answer. They don't check that the server speaks the protocol, survives what models actually send, or still matches what clients expect after a release. A black-box harness, a seeded fuzzer and a snapshot diff cover those three.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 7 · Lessons 2 and 3; Phase 2 · Lesson 11
**Time:** ~40 minutes

## Learning Objectives

- Build a black-box conformance harness that tests any stdio MCP server command against protocol rules.
- Generate seeded, schema-guided fuzz arguments that mimic a confused model, and check the server never crashes, hangs or returns malformed results.
- Diff tool-list snapshots between releases and flag breaking changes.
- Recognise the most common server bugs from the harness output.

## The Problem

Phase 2 · Lesson 11 tested tools as functions. A server can pass all of those tests and still fail in a host:

- It prints a startup banner to stdout, and strict clients drop it (Lesson 2).
- It returns the request id `4242` as the string `"4242"`, and the client never matches the response.
- It crashes on `{"a": "1"}` because nobody validated types, and models do send strings for integers.
- It has a non-daemon thread, so it never exits when the host closes it, and zombie processes pile up.
- A release makes an optional parameter required, and every agent prompt that worked yesterday now gets errors.

None of these are about what a tool computes. They're about the server as a protocol participant and as a contract with its clients. The only way to catch them is to drive the real process the way a host does.

## The Concept

```
 conformance harness (black box)                 any stdio server command
 ┌──────────────────────────────────┐   stdin   ┌────────────────────┐
 │ protocol checks: discover, ids,  │ ────────► │                    │
 │   error codes, _meta, versions   │           │   server under     │
 │ listing checks: order, cache     │ ◄──────── │   test             │
 │   fields, names, schemas         │   stdout  │                    │
 │ seeded fuzzing from inputSchema  │           └────────────────────┘
 │ hygiene: stdout, latency, exit   │
 └──────────────────────────────────┘
 snapshot diff: tools/list (release N) vs tools/list (release N+1) -> BREAKING / ok / review
```

| Layer | What it catches | Speed |
|-------|----------------|-------|
| Unit tests on handlers | Wrong answers, bad edge cases | Milliseconds |
| Conformance harness | Protocol violations, crashes, hygiene | Seconds |
| Seeded fuzzing | Inputs nobody thought of; crashes on wrong types | Seconds, reproducible |
| Snapshot diff | Breaking changes to the tool contract | Milliseconds |
| Evals with a real model | Whether models use the tools well (Phase 11) | Minutes, costs money |

**Fuzzing for MCP** isn't random bytes. It's mostly-valid arguments built from each tool's `inputSchema`, with a share of what models really get wrong: strings for numbers, missing or extra fields, very long or empty strings, values outside an enum, nulls. A seed makes every failure reproducible.

**Breaking changes** to a tool are changes that make yesterday's valid call invalid or different: removing a tool or parameter, making a parameter required, narrowing a type or enum. Adding an optional parameter or a new tool is safe. Changing a description is safe for the protocol but can change model behaviour, so it deserves a review.

## Build It

```bash
cd code
python3 main.py
```

Two bundled servers: `good` and `buggy`. The buggy one has eleven common bugs, each marked `# bug:` in the code. To test your own server: `python3 main.py -- python3 path/to/server.py`.

### Step 1: drive the process like a host

`Proc` spawns the command, reads stdout on a thread, and sorts each line into parsed messages or junk. When stdout closes it posts an end-of-stream marker, so a crashed server is noticed at once instead of after a timeout.

### Step 2: protocol checks

```python
r = p.request("server/discover", mid=4242)
check("response id echoes request id (type too)", isinstance(r, dict) and r.get("id") == 4242 and type(r["id"]) is int, ...)
check("unknown method -> -32601", err_code(p.request("bogus/method")) == -32601)
check("missing _meta -> -32602", err_code(p.request("tools/list", meta=False)) == -32602)
```

Each check is one line and one rule. A failure prints the rule and what actually happened.

### Step 3: schema-guided fuzzing

```python
def fuzz_value(spec, rng):
    roll = rng.random()
    if roll < 0.15:
        return rng.choice([None, "7", 7, 3.5, True, [], {}, "x" * 500])
    ...
    if t == "string":
        return rng.choice(["", "Ana", "名前", "a\nb", "'; DROP TABLE x;--", "x" * rng.randint(1, 60)])
```

The harness sends 40 calls and requires every reply to be a well-formed result (`content` list, boolean `isError`). If the server dies, it's counted and restarted so the remaining checks still mean something.

### Step 4: the report

```text
good server: 18/18 checks pass
  PASS  server/discover lists the current version
  PASS  results carry resultType
  PASS  response id echoes request id (type too)
  PASS  unknown method -> -32601
  PASS  missing _meta -> -32602
  PASS  unsupported version -> -32022 with supported list
  PASS  malformed JSON -> -32700, server keeps going
  PASS  notifications get no reply
  PASS  tools/list order is stable
  PASS  tools/list has ttlMs and cacheScope
  PASS  tool names valid, inputSchema is an object
  PASS  unknown tool -> -32602
  PASS  fuzz: 40 schema-guided calls, no crash or hang
  PASS  fuzz: every reply well-formed
  PASS  wrong argument type -> isError result
  PASS  tools/list under 100 ms
  PASS  stdout carries only JSON-RPC
  PASS  exits within 2s when stdin closes
```

```text
buggy server: 6/18 checks pass
  PASS  server/discover lists the current version
  FAIL  results carry resultType
  FAIL  response id echoes request id (type too)  (sent 4242, got '4242')
  PASS  unknown method -> -32601
  FAIL  missing _meta -> -32602
  FAIL  unsupported version -> -32022 with supported list
  FAIL  malformed JSON -> -32700, server keeps going  (no reply within 1s)
  PASS  notifications get no reply
  FAIL  tools/list order is stable
  FAIL  tools/list has ttlMs and cacheScope
  PASS  tool names valid, inputSchema is an object
  FAIL  unknown tool -> -32602
  FAIL  fuzz: 40 schema-guided calls, no crash or hang  (9 crashed the server, 0 hung)
  PASS  fuzz: every reply well-formed
  FAIL  wrong argument type -> isError result  (no reply)
  PASS  tools/list under 100 ms
  FAIL  stdout carries only JSON-RPC  (junk: 'buggy-server v0.1 starting')
  FAIL  exits within 2s when stdin closes
```

Read the failures as a to-do list. The banner and the shutdown hang are one-line fixes. "No reply within 1s" for malformed JSON means a client would wait for its timeout on every bad line. Nine of forty fuzzed calls killed the process: in a host, each one takes the server's tools away until it restarts (Lesson 9).

### Step 5: snapshot diff

Store `tools/list` from the last release in the repo, and diff it in CI:

```text
Snapshot diff between releases
  BREAKING tool removed: tag
  ok       tool added: farewell
  ok       add: optional parameter 'c' added
  BREAKING greet: 'lang' is now required
  BREAKING greet: 'lang' no longer accepts ['hi']
  review   greet: description changed (models may behave differently)
```

A BREAKING line should fail the build unless the release is meant to break things, in which case it needs a new tool name or a deprecation period. The "review" line is a reminder that a description is a prompt: "Always use French unless told otherwise" will change what models do, even though no schema changed.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Tool | Role |
|------|------|
| MCP Inspector | Interactive: connect, list, call, and watch the JSON-RPC traffic |
| SDK in-memory transports | Fast tests of a server without spawning a process |
| This harness (or a conformance suite) in CI | Every server, every commit, black-box |
| Property-based testing libraries (Hypothesis and similar) | Richer fuzzing from schemas |
| Model evals (Phase 11) | Whether real models pick and use the tools correctly |

## Ship It

`outputs/skill-mcp-server-testing.md` is a skill for testing an MCP server before release: a conformance checklist, seeded schema-guided fuzzing, hygiene checks (stdout, shutdown, latency), a tool-list snapshot with breaking-change rules, and where each layer runs in CI.

## Exercises

1. **Easy.** Fix three of the buggy server's bugs and re-run. Which checks flip to PASS?
2. **Medium.** Add a check that `structuredContent`, when present, matches the tool's `outputSchema` (Lesson 3).
3. **Medium.** When a fuzz call crashes the server, shrink the arguments (drop keys one at a time, shorten strings) to the smallest input that still crashes it, and print that.
4. **Hard.** Port the harness to Streamable HTTP (Lesson 6): add header checks (-32020 on mismatch), status codes, and an Origin check. Which stdio checks no longer apply?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Conformance test | "Protocol test" | A black-box check that a server follows the protocol's rules |
| Schema-guided fuzzing | "Fuzz the tools" | Generating mostly-valid and deliberately wrong arguments from `inputSchema`, with a seed |
| Snapshot test | "Golden file" | Saving `tools/list` output and diffing it against the next release |
| Breaking change | "Broke the API" | A change that makes a previously valid call fail or behave differently |
| Hygiene checks | "Ops checks" | Clean stdout, exit on stdin close, reasonable latency |

## Further Reading

- [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
- [MCP specification 2026-07-28: Base protocol](https://modelcontextprotocol.io/specification/2026-07-28/basic)
- [Hypothesis: property-based testing for Python](https://hypothesis.readthedocs.io/)
- [Semantic Versioning](https://semver.org/)
- [Google, OSS-Fuzz documentation](https://google.github.io/oss-fuzz/)
