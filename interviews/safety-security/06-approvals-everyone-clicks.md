# Approval prompts that everyone clicks through

> After an incident, every external action by your ops agent requires human approval. Two months later, logs show reviewers approve 99% of requests with a median decision time under one second. An injected request to pay a new bank account was approved last week. What went wrong, and how do you redesign approvals?

**Level:** 3
**Type:** Trade-off
**Time:** ~10 minutes
**Taught in:** 12-safety-and-security/09-human-in-the-loop-design, 02-tool-use/08-human-approval-gates

## Short answer

Approval fatigue: when almost every action asks and almost every answer is yes, people stop reading, and the approval stops being a check. Redesign for fewer, better prompts. Approve a plan up front and only ask for deviations and high-risk irreversible actions. Replace approvals the human can't add information to with automated checks. Make each card show what's unusual ("new IBAN, first payment to this supplier"). Bind approvals to the facts shown, expire them, and re-check before acting. Monitor decision time and approval rates as health metrics.

## Full answer

### Why it failed

- Volume: dozens of routine prompts per day.
- Low information: cards showed the action, not what was unusual about it.
- No consequences visible: the risky request looked like the others.

### Ask only where a human adds information

| Action | Better control |
|--------|----------------|
| Routine, reversible (edit under git, internal note) | No prompt; audit log |
| Checkable by code (tests pass, schema valid) | Automated verifier |
| Irreversible and unusual (new payee, first-time recipient, large amount) | Human, with the unusual facts highlighted |
| Within an approved plan | No prompt; deviations ask |

### Make cards useful

User's original request, the exact action, why it's flagged, what differs from normal (new account, amount above typical), source of the instruction (was untrusted content read?), and the consequence of approving.

### Make approvals durable and safe

Persist requests, expire unanswered ones to "no", fingerprint the facts, and re-ask if they change before execution.

### Monitor

Approval rate, decision time, approvals per reviewer per day. Sub-second approvals and near-100% rates are alarms.

## Follow-ups

- **L3.** How would you compare approval policies before rolling one out? *Expected:* Replay a week of actions with labels for harmful ones; count prompts and harmful actions shown, and test sensitivity to assumptions about reviewer attention.
- **L3.** Should high-value payments need two approvers? *Expected:* Often yes for irreversible high-value actions, with independent reviewers and the facts highlighted; keep it rare.
- **L4.** What should happen when nobody approves for 24 hours? *Expected:* Expire to no, notify the requester, and resume only with a fresh request and re-checked facts.

## Wrong answers

- "Train reviewers to be more careful." Attention doesn't scale with volume; reduce the volume.
- "Require approval for even more actions." Increases fatigue and makes the important prompt less visible.
- "Remove approvals; they don't work." They work when rare and informative; the design was the problem.
