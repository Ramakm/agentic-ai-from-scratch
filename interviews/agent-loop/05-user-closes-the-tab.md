# The user closes the tab halfway through a ten-minute task

> Your agent runs long tasks: research, multi-file edits, data pulls. Runs live in the web server process. Users close tabs, deploys restart servers, and sometimes the agent needs approval from someone who isn't online. All of these lose the run today. Design how runs survive.

**Level:** 3
**Type:** Design
**Time:** ~15 minutes
**Taught in:** 03-the-agent-loop/08-interrupts-and-resumption, 12-safety-and-security/09-human-in-the-loop-design, 03-the-agent-loop/09-state-machines-for-agents

## Short answer

Decouple runs from requests. A run is a durable record (task, messages, step, status, pending actions) in a database, executed by workers, with the UI subscribing to its events. Checkpoint after every step, so a crash resumes from the last completed step. Make side-effecting steps idempotent so a step re-run after a crash doesn't repeat effects. Model pauses explicitly (waiting for approval, waiting for user input), persisted with an expiry. Interrupts from the user become events the loop checks between steps.

## Full answer

### Architecture

| Piece | Role |
|-------|------|
| Run store | One row per run: status, step, messages or a pointer to them, budget used |
| Queue + workers | Pick up runnable runs; one worker per run at a time (lease or lock) |
| Event stream | Steps, tool calls, partial output to the UI over SSE or websockets |
| Checkpoints | After each completed step; the unit of resumption |
| Pending actions | Approvals and questions for the user, with expiry and the facts they were based on |

### Statuses

`queued → running → (waiting_approval | waiting_user) → running → completed | failed | cancelled | expired`. A state machine makes the allowed transitions explicit and testable.

### The tricky parts

- **Exactly-once side effects.** A crash after the payment API succeeded but before the checkpoint means the step re-runs. Idempotency keys make the re-run harmless.
- **Stale approvals.** Re-check the facts on resume; if they changed, ask again.
- **Interrupts mid-step.** Let the current tool call finish or cancel it cleanly; check the interrupt flag between steps.
- **Long histories.** Store messages separately; compact before resuming very long runs.
- **Versioning.** A run started on prompt v3 may resume after v4 deploys; record the version and decide whether to continue or restart.

### Off-the-shelf

LangGraph checkpointers, durable execution engines (Temporal and similar), or a jobs table you own. The concepts are the same.

## Follow-ups

- **L3.** Where does the model's in-flight call go when a worker dies? *Expected:* It's lost; the step re-runs from the last checkpoint. Model calls are retried; only side effects need idempotency.
- **L3.** How do you stop two workers running the same run? *Expected:* A lease with heartbeat in the run store, or the queue's visibility timeout; the step write is conditional on holding the lease.
- **L4.** How would you test resumption? *Expected:* Fault injection: kill workers at each point in a step (before tool, after tool, before checkpoint) and assert final state and side effects match a clean run.

## Wrong answers

- "Keep the websocket open and ask users not to close the tab." Deploys and crashes still kill runs.
- "Save the transcript at the end." A crash loses everything; checkpoint every step.
- "Just re-run the task from scratch on failure." Repeats side effects and wastes the work done.
