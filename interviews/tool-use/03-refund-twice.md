# The customer got refunded twice

> Your agent's `issue_refund` tool calls the payments API. A request times out, your client retries, and the agent also decides to call `issue_refund` again because the first call "failed". The customer is refunded twice. How do you prevent this class of bug?

**Level:** 2
**Type:** Debug
**Time:** ~8 minutes
**Taught in:** 02-tool-use/07-idempotency-and-side-effects, 02-tool-use/05-tool-errors-as-observations

## Short answer

Make side-effecting tools idempotent. Derive an idempotency key from the business intent (for example `refund:order-1001:reason-damaged`), not from the attempt, and send it with every call so the payments API (or your own ledger) returns the original result for a repeat instead of acting again. Distinguish "failed" from "unknown": on a timeout, the tool should check the state (was a refund created?) before reporting, and tell the model the truth. Limit the agent so the same side effect can't be requested twice in a task without a check.

## Full answer

### Why agents make this worse

Two retry layers stack: your HTTP client retries, and the model retries because it saw an error. Neither knows the first attempt might have succeeded. A timeout means "unknown", not "failed".

### Idempotency keys

| Choice | Result |
|--------|--------|
| Random key per attempt | Useless: every retry looks new |
| Key per tool call id | Protects against client retries, not the model calling again |
| Key from intent (order, action, amount or reason) | Protects against both |

Many payment APIs support idempotency keys natively. If yours doesn't, keep a ledger table keyed by intent and check it before acting.

### Report the truth

On timeout: query for the effect (`get_refunds(order_id)`). Return `refund already exists (R-881, $49.00)` or `no refund found; safe to retry`. The model decides well when it's told what's true.

### Separate reads from writes

Mark tools as read-only or side-effecting. Side-effecting tools get idempotency, stricter limits, maybe approval. Reads can retry freely.

## Follow-ups

- **L2.** How do you test this? *Expected:* A fake API that times out after committing; assert one refund after retries by the client and the model. Same for concurrent duplicate calls.
- **L3.** The agent legitimately needs two partial refunds on one order. Does the intent key break that? *Expected:* Include what distinguishes them (amount, line item, a reason) or a sequence the user confirms; the key encodes "this specific refund".
- **L3.** What about side effects with no idempotency support, like sending an email? *Expected:* An outbox: record the intent first, send once from the outbox, and mark it sent; on retry, check the outbox.

## Wrong answers

- "Turn off retries." Then transient failures fail tasks, and the model still retries on its own.
- "Tell the model never to call issue_refund twice." It doesn't know whether the first one happened; neither do you without a check.
- "Use a random UUID as the idempotency key." A new key per attempt defeats the purpose.
