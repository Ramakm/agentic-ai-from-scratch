# The agent needs database access

> A support agent needs to answer questions about customers' orders and issue small refunds. The quickest path is a `run_sql(query)` tool with the app's database credentials. What do you build instead?

**Level:** 2
**Type:** Design
**Time:** ~10 minutes
**Taught in:** 12-safety-and-security/04-least-privilege-tools, 02-tool-use/06-designing-tools-models-can-use, 12-safety-and-security/08-secrets-and-credentials

## Short answer

Narrow, session-bound tools. Build `list_my_orders()`, `get_order(order_id)` and `refund_order(order_id, amount)` by a factory that runs when the session starts and captures the authenticated customer's id, the refund cap and the database handle in closures, so the model never passes identity or limits. Every query is parameterised and filtered by that customer. Refunds are capped by the order's remaining amount and a policy limit in code. The tools connect with a database role that can only do those operations. Then the worst a manipulated model can do is the customer's own allowed actions.

## Full answer

### Why `run_sql` fails

The prompt says "only this customer's orders"; the tool can do anything. One injection or persuasive user and it reads another tenant's data, rewrites totals, or drops tables.

### Bind, don't ask

| Decision | Broad tool | Narrow tool |
|----------|------------|-------------|
| Whose data | Model writes `WHERE user = …` | Bound from the session |
| How much | `UPDATE … SET refunded = total` | Capped in code |
| Which operation | Any SQL | Only the operations that have a tool |
| Where data goes | Anywhere | Back to this customer only |

### Defence in depth

1. **Tool layer:** narrow tools, parameterised queries, ownership checks, caps.
2. **Credential layer:** a DB role with SELECT on orders and UPDATE on the refund column only; no DDL.
3. **Data layer:** row-level security per tenant if the database supports it.
4. **Runtime:** no network path to other databases or metadata endpoints.

### When ad-hoc SQL is truly needed

For internal analytics agents: a read-only role over views already filtered by tenant, statement timeouts, row limits and logging.

## Follow-ups

- **L2.** Why return "amount must be between 0 and 49.00" instead of "denied"? *Expected:* Errors are observations; a precise range lets legitimate use succeed on retry without weakening the check.
- **L3.** A support *employee* uses the agent and may see any order in their region. How does the design change? *Expected:* The factory takes the employee's role and region from auth; tools filter by region; still no identity parameters for the model.
- **L3.** How would you audit a toolset for this problem? *Expected:* Flag parameters that pick identity, tenant, resource by free text, destination or unbounded amounts.

## Wrong answers

- "Use run_sql and tell the model which customer it's serving." The prompt is a request; the tool is a capability.
- "Validate the SQL with a regex for DROP and DELETE." SQL is too expressive to blacklist safely, and reads of other tenants aren't caught.
- "Use a read-only connection and you're safe." Read-only still leaks other customers' data.
