# The agent paid the wrong supplier. Investigate.

> Finance reports that your finance agent paid €8,400 to a bank account nobody recognises. You're the incident lead. Walk through the first hours: what you check, what you need from your logs, and what changes you'd expect to make afterwards.

**Level:** 4
**Type:** Design
**Time:** ~20 minutes
**Taught in:** 12-safety-and-security/11-audit-logs, 12-safety-and-security/02-prompt-injection-direct-indirect, 12-safety-and-security/09-human-in-the-loop-design

## Short answer

Contain first: pause the agent's payment capability, contact the bank to try to recall the payment, and preserve logs. Then reconstruct the causal chain from the audit log: the payment call, the decision that allowed it (rule, approver, what they were shown), and what led to the call, walking cause links back to the user's request. In this kind of incident you typically find an untrusted input (an email "updating bank details") that the agent acted on, plus an approval that didn't highlight the new account. Afterwards: verify payee changes out-of-band, gate new payees in code, improve approval cards, add the attack to the red-team suite, and confirm the audit log answered every question.

## Full answer

### Hour 0–1: contain

- Disable `pay_invoice` (feature flag) for all sessions.
- Notify finance and the bank; time matters for recalls.
- Freeze and copy the logs; verify the audit log's integrity (hash chain and anchor).

### Reconstruct with the audit log

| Question | Where the answer comes from |
|----------|-----------------------------|
| What exactly was paid, to whom, when? | `tool_call` entry for `pay_invoice` and its result |
| Who allowed it? | `decision` entry: rule, layer, approver, hash of the card shown |
| What caused it? | Walk `cause` links: payment ← email read ← list invoices ← user request |
| Was untrusted content involved? | Trust labels on tool results |
| Did anything else happen in that session or others? | Query by session, by IBAN, by sender domain |

If you can't answer one of these, that's a logging finding in itself.

### Likely root causes

1. **Indirect injection:** an attacker email announcing new bank details, read in the same session that can pay.
2. **Missing business control:** payee changes weren't verified against the supplier master record.
3. **Weak approval:** the card didn't flag the new IBAN; the approver was fatigued.

### Fixes

- **Code control:** payments only to IBANs on the verified supplier record; changes go through a separate, out-of-band verified process.
- **Session design:** the session that reads email can't pay; payments use structured data only.
- **Approval cards** highlight new payees and amounts above normal.
- **Red-team case** for "changed bank details" emails, in the regression suite.
- **Blameless postmortem**, with timeline from the audit log.

## Follow-ups

- **L3.** What's the difference between your traces and your audit log here? *Expected:* Traces may be sampled, mutable and content-heavy; the audit log is complete, tamper-evident, minimal and records decisions and causes.
- **L4.** How do you tell whether other payments were affected? *Expected:* Query the audit log for payments following untrusted inputs, new payees, or the attacker's sender domain across all sessions.
- **L4.** What would you report to leadership? *Expected:* Impact, timeline, root causes (technical and process), what's fixed, what's left, and how you'll know it's working.

## Wrong answers

- "The model made a mistake; switch models." The design let untrusted input drive a payment to an unverified account.
- "Fire the approver." Approval fatigue is a system design problem.
- "Add 'never change bank details' to the prompt." Payee verification belongs in code and process.
