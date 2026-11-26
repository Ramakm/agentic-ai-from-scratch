# Audit Logs

> When an agent does something it shouldn't have, you will be asked three questions: what exactly happened, who allowed it, and what made the agent do it. A trace helps you debug. An audit log answers those questions in a way nobody, including the agent's own operators, could have quietly edited afterwards.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 11 · Tracing with OpenTelemetry; Phase 12 · Permission systems
**Time:** ~35 minutes

## Learning Objectives

- Explain how an audit log differs from a trace: purpose, contents, retention, and who may change it.
- Record agent events with actor, cause and decision, so "why did the agent do X?" is a walk up the cause links.
- Make the log tamper-evident with an HMAC hash chain plus an external anchor, and detect edits, deletions, reordering and truncation.
- Minimise what's stored: omit secrets, hash content, and still prove later which content was involved.

## The Problem

Finance asks why the agent paid €8,400 to an IBAN nobody recognises. You open your traces. They show the tool call, but the spans from that hour were sampled out except one. The email the agent read was logged in full, including the supplier's bank details and a customer's address, so the trace store is now a privacy problem of its own. The approval isn't in the trace at all; it lived in a Slack thread. And when the security team asks whether anyone could have edited these records, the honest answer is "anyone with write access to the log bucket".

You need a record built for investigations: complete, linked by cause, minimal in content, and tamper-evident.

## The Concept

### Trace vs audit log

| | Trace (Phase 11) | Audit log |
|-|------------------|-----------|
| Question | Why was it slow or wrong? | Who did what, for whom, under which permission, caused by what? |
| Completeness | Sampled | Every security-relevant event, never sampled |
| Content | Full prompts and results help | Minimal: ids, hashes, decisions; secrets never |
| Mutability | Engineers can delete or rewrite | Append-only; changes are detectable |
| Retention | Days to weeks | Months to years, per policy or regulation |
| Readers | Engineers | Security, compliance, auditors, sometimes courts |

### What to record

| Event | Must include |
|-------|--------------|
| user_message | Who (user, agent version, session), content hash |
| tool_call | Tool, arguments with secrets omitted, **cause**: the entry that led to it |
| tool_result | Trust level (internal / untrusted), content hash and length |
| decision | allow / ask / deny, the rule and layer (Lesson 6), the approver, a hash of what they were shown (Lesson 9) |

The `cause` field is what makes investigations fast. The payment's cause is the untrusted email; the email's cause is the call that read it; and so on up to the user's request.

### Tamper evidence

Each entry stores the previous entry's MAC, and its own MAC is an HMAC over its contents with a key the log service holds and the agent doesn't:

| Change | How it's detected |
|--------|-------------------|
| Edit an entry | Its MAC no longer matches its contents |
| Delete or insert | Sequence numbers and `prev` links break |
| Reorder | Same |
| Truncate the tail | Invisible to the chain alone. Caught by an **anchor**: the head (count + last MAC) published somewhere else |
| Rewrite everything | Needs the key; without it, every MAC fails |

This is tamper-*evident*, not tamper-*proof*. Someone can still delete the file. Ship entries to append-only storage (object lock, a separate account) as they're written.

### Minimise content

Hash content instead of storing it: `{"hash": "sha256:...", "chars": 140}`. You can't read the email from the log, but given the email from the mail server you can prove it's the one the agent read. Store full content, if at all, in a separate restricted store with shorter retention.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: append with a chain

```python
prev = self.entries[-1]["mac"] if self.entries else "genesis"
body = {"seq": len(self.entries), "ts": ts, "event": event, "actor": actor,
        "cause": cause, "data": self._minimise(data), "prev": prev}
body["mac"] = hmac.new(self.key, canonical(body), hashlib.sha256).hexdigest()
```

`canonical` serialises with sorted keys and fixed separators, so the same entry always produces the same bytes.

### Step 2: minimise before writing

```python
if SECRET_ARG.search(k):
    out[k] = "[omitted]"
elif k in ("content", "body") and isinstance(v, str):
    out[k] = {"hash": digest(v), "chars": len(v)}
```

### Step 3: verify

```python
if e.get("seq") != i:
    return False, f"entry {i}: sequence number is {e.get('seq')} (deleted or reordered)"
if e["prev"] != prev:
    return False, f"entry {i}: doesn't follow entry {i - 1} (deleted, inserted or reordered)"
if not hmac.compare_digest(e["mac"], hmac.new(self.key, canonical(body), hashlib.sha256).hexdigest()):
    return False, f"entry {i}: contents changed after it was written"
```

### Step 4: ask why

```python
def why(self, seq: int) -> list[dict]:
    chain = []
    while seq is not None:
        e = self.entries[seq]
        chain.append(e)
        seq = e["cause"]
    return chain
```

### Output

```text
log:
  #0 user_message               
  #1 tool_call    list_invoices {"week": "2025-W14"}
  #2 tool_result  list_invoices {"trust": "internal"}
  #3 tool_call    read_email    {"id": 4411}
  #4 tool_result  read_email    {"trust": "untrusted"}
  #5 tool_call    pay_invoice   {"invoice": "INV-91", "amount": 8400, "iban": "GB33 BUKB 2020 1555 5555 55", "api_key": "[omitted]"}
  #6 decision     approved      ask pay_invoice [org]
  #7 tool_result  pay_invoice   {"trust": "internal"}

published anchor: 8:f0cb61be3c7937856c9174...
verify: (True, '8 entries, chain intact')

why did the agent call pay_invoice?
  #5 tool_call    pay_invoice   {"invoice": "INV-91", "amount": 8400, "iban": "GB33 BUKB 2020 1555 5555 55", "api_key": "[omitted]"}
  #4 tool_result  read_email    {"trust": "untrusted"}
  #3 tool_call    read_email    {"id": 4411}
  #2 tool_result  list_invoices {"trust": "internal"}
  #1 tool_call    list_invoices {"week": "2025-W14"}
  #0 user_message               

tampering:
  change the amount in #5          (False, 'entry 5: contents changed after it was written')
  delete the untrusted email #4    (False, 'entry 4: sequence number is 5 (deleted or reordered)')
  swap #6 and #7                   (False, 'entry 6: sequence number is 7 (deleted or reordered)')
  drop the last entry              (False, 'log has 7 entries but the anchor says 8 (truncated)')
  drop the last entry, no anchor   (True, '7 entries, chain intact')

what the log kept about the email: {'hash': 'sha256:788d3ba4a593ee39', 'chars': 140}
is this the email that was read?   True
api_key in the log:                [omitted]
```

The investigation takes one call: the payment's direct cause is an **untrusted** email (#4), the IBAN in the call is not one from the invoice list, and the decision entry shows a human approved it under the org rule. That points at two fixes: the IBAN should have been checked against the supplier record (Lesson 4), and the approval card should have shown that the IBAN was new (Lesson 9).

Note the last two tampering lines: dropping the final entry passes the chain check on its own. Only the published anchor reveals it.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Tool or practice | What it gives you |
|------------------|-------------------|
| AWS CloudTrail log file integrity validation | Hash-chained digest files signed by AWS, the same idea at cloud scale |
| S3 Object Lock, WORM storage, a separate logging account | Storage the agent's operators can't rewrite |
| Transparency logs (Certificate Transparency, Sigstore Rekor) | Public Merkle-tree logs; a natural place to anchor heads |
| SIEM (Splunk, Elastic, Sentinel) | Search, alerting and retention for audit events |
| OpenTelemetry GenAI conventions | Good for traces; export a minimised subset to the audit log, don't treat traces as one |
| EU AI Act, Article 12 | High-risk AI systems must automatically record events over their lifetime |

## Ship It

`outputs/skill-agent-audit-log.md` is a skill for designing an agent audit log: the event list with required fields, minimisation rules, the chain and anchoring scheme, storage and retention, and the "why" queries investigators will run.

## Exercises

1. **Easy.** Add an event for a denied tool call. Run `why` on it.
2. **Medium.** Anchor every 100 entries instead of only at the end, and make `verify` check every anchor. What does that buy you over one final anchor?
3. **Medium.** Split the key: the agent process gets a write-only client that sends events to a log service, which computes MACs. Sketch the interface. What can a compromised agent still do?
4. **Hard.** Replace the linear chain with a Merkle tree (as in RFC 6962) so you can prove one entry is in the log without revealing the others. Implement the inclusion proof for one entry.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Audit log | "Logs" | An append-only record of security-relevant events, built for investigation |
| Hash chain | "Blockchain-style log" | Each entry includes the previous entry's hash, so changes break the chain |
| HMAC | "Signed hash" | A keyed hash; without the key you can't produce valid ones |
| Anchor | "Checkpoint" | The log head published elsewhere, so truncation or rewriting is detectable |
| Causal link | "Parent id" | The entry that led to this one, so actions trace back to their trigger |
| Data minimisation | "Log less" | Storing hashes and ids instead of content, and never storing secrets |

## Further Reading

- [Schneier & Kelsey, Secure audit logs to support computer forensics (1999)](https://www.schneier.com/academic/archives/1999/01/secure_audit_logs_to.html)
- [AWS, Validating CloudTrail log file integrity](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html)
- [RFC 6962, Certificate Transparency](https://www.rfc-editor.org/rfc/rfc6962)
- [OWASP, Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- [OpenTelemetry, semantic conventions for generative AI](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [EU AI Act, Article 12: record-keeping](https://artificialintelligenceact.eu/article/12/)
