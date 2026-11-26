---
name: least-privilege-tools
description: >
  Review and rewrite an agent's tools for least privilege. Flags parameters that let the
  model choose identity, tenant, resource, destination or unbounded amounts, and rewrites
  broad tools (run_sql, http_get, read_file, send_email, run_shell) as session-bound narrow
  ones. Use when designing tools, reviewing an agent before launch, or after an incident.
---

# Least-privilege tool review

## 1. For each tool, for each parameter, ask

| Question | If yes |
|----------|--------|
| Does it pick whose data this is (user, tenant, account)? | Remove it. Bind from the session. |
| Does it pick a resource by free text (SQL, URL, path, command)? | Replace with an id or slug validated against a fixed set |
| Does it pick a destination (email, channel, webhook, repo)? | Fix it, or allow-list it per session |
| Is it an amount, count or size? | Cap it in the tool from data and policy |
| Is it free text that ends up somewhere public? | Treat as an egress channel (Lesson 3) |

## 2. Rewrite as a factory
```python
def tools_for(session) -> dict[str, Callable]:
    # session.user, session.tenant, session.limits come from auth, not the model
    def get_order(order_id: str): ...   # WHERE id = ? AND user = ?
    return {...}
```
Parameterise every query. Return errors that state the valid range.

## 3. Check the lower layers
- The credential each tool uses: can it do more than the tool exposes? Narrow it.
- The runtime: can the process reach metadata endpoints, internal hosts, the filesystem?

## 4. Prove it
Write one attack per removed capability (other tenant, rewrite, destroy, secrets, exfil,
SSRF) and run it against old and new toolsets. Also run the legitimate tasks. Report both.
