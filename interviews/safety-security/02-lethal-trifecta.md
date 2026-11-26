# Which of these three agents is dangerous?

> You review three designs. A: a public docs bot that searches your published docs. B: an inbox assistant that reads mail, searches Drive, fetches URLs and can send email. C: a coding agent that reads GitHub issues, reads repo files including `.env`, and runs shell commands. Rank them by injection risk and explain the reasoning you'd use for any agent.

**Level:** 2
**Type:** Concept
**Time:** ~8 minutes
**Taught in:** 12-safety-and-security/01-the-agent-threat-model, 12-safety-and-security/03-data-exfiltration-paths

## Short answer

Use the lethal trifecta: an agent session is exposed when it (1) reads private data, (2) takes in content an attacker can write, and (3) can send data out. With all three, attacker text can make it read a secret and leak it. A has none of the legs worth worrying about: low risk. B has all three (email is both private and attacker-written; `fetch_url` and `send_email` are egress; a markdown-rendering UI is egress too). C also has all three: issues are attacker-written, `.env` is private, and the shell can reach the network; plus irreversible actions. So B and C are high risk; fix them by cutting a leg per session.

## Full answer

### Classify every tool

| Agent | Untrusted | Private | Egress | Irreversible |
|-------|-----------|---------|--------|--------------|
| A docs bot | – | – | – | – |
| B inbox | read_email, fetch_url | read_email, search_drive | fetch_url, send_email, rendered images | send_email |
| C coding | read_issue | read_file, run_shell | run_shell, git push, rendered images | run_shell, git push |

One tool can sit on two legs. The UI counts if it renders markdown images.

### A second path

Untrusted input plus an irreversible action is dangerous even without private data: "reply-all saying the meeting is cancelled".

### Cutting a leg

| Agent | Practical cut |
|-------|---------------|
| B | Cut egress: approval for send, allow-listed fetch, images only from your domain |
| C | Cut untrusted: triage issues in a separate session with no shell or secrets, pass a structured summary; plus a sandbox without secrets |

Meta's "Agents Rule of Two" states the same principle: at most two of untrusted input, sensitive access and external actions per session without human approval.

## Follow-ups

- **L2.** Why is the rendered UI an egress channel? *Expected:* A markdown image URL is fetched automatically when displayed; data in the query string leaves with no click.
- **L3.** Which leg would you usually cut, and why? *Expected:* Egress or untrusted input; private data is usually the product's purpose.
- **L3.** How does splitting sessions help C? *Expected:* The session that reads attacker text has no secrets or shell; the session with the shell sees only a typed summary, so injected text can't drive tool calls.

## Wrong answers

- "C is safe because developers use it, not customers." Issues and dependencies are written by outsiders.
- "B is safe because the model is told not to follow email instructions." Prompts don't remove a leg.
- "A is dangerous because anyone can talk to it." It can be manipulated into saying things, but it can't leak private data or act.
