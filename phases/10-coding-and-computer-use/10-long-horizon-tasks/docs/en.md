# Long-Horizon Tasks

> Some tasks don't fit in one context window, and some processes don't live long enough to finish them. Put the task's memory on disk instead: a todo list, progress notes and checkpoints. Start every session fresh from that state. Mark an item done only after a check passes. Force a handoff before the context fills. When a session dies mid-item, the next one re-checks that item before trusting it.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 10 · Test-driven agent loops; Phase 4 · Files as long-term memory; Phase 4 · Context compaction; Phase 3 · Interrupts and resumption
**Time:** ~50 minutes

## Learning Objectives

- Keep a long task's state on disk (todo list, notes, checkpoints) so any session, or any process, can continue it.
- Bound context per session with a harness-enforced handoff, and compare against one unbounded session.
- Make "done" mean "verified": mark items done only after a check passes since the last edit.
- Recover from a crash mid-item by re-verifying `in_progress` items first, with atomic writes so the state file is never corrupt.

## The Problem

"Migrate all 200 modules from `print` to `logging`." An agent starts well. By module 40 its context is full of old diffs and test output; quality drops, it forgets the pattern it settled on, and it starts re-editing files it already did. At module 73 the laptop sleeps, the process dies, and when you restart there's no record of which modules are done, which are half-done, or why module 51 was skipped.

Long tasks fail for two separate reasons: **context** (one window can't hold the whole history) and **lifetime** (one process can't be trusted to survive). The fix for both is the same: the agent's memory of the task lives in files, not in its context.

## The Concept

| State | File | Written when | Read when |
|-------|------|--------------|-----------|
| What's left, what's done, what's half-done | `todo.json` | Item started, item verified | Start of every session |
| Decisions, patterns, gotchas | `PROGRESS.md` | Handoffs, discoveries | Start of every session |
| How to undo an item | `.checkpoints/<item>/` | Item started | Rollback |

**Item lifecycle:**

| Status | Meaning | Next session does |
|--------|---------|-------------------|
| `pending` | Not started | Start it |
| `in_progress` | Started; maybe half-edited, maybe finished but unverified | **Run the check first**, then fix or mark done |
| `done` + `verified` | Check passed after the last edit | Skip |

**Session loop:** fresh context = instructions + `PROGRESS.md` + the remaining todo items. Work item by item. When the transcript passes the budget, the harness says "write a note and stop". The next session starts from files, not from the transcript.

## Build It

```bash
cd code
python3 main.py
```

The demo migrates 8 modules with a 6,000-character context budget and kills the process in session 2 right after editing `mod_04`.

### Step 1: state that survives crashes

```python
def save_todo(self, items):
    tmp = self.todo_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1))
    tmp.replace(self.todo_path)                     # atomic: a crash never leaves half a todo file
```

Write to a temp file, then rename. A rename is atomic on POSIX filesystems, so the todo file is always either the old version or the new one.

### Step 2: done means verified

```python
def mark_done(self, id):
    if not self.last_check.get(rel):
        return f"error: run_check({id!r}) must pass after the last edit before it can be marked done"
```

The same rule as Lesson 1, applied per item: edits clear the item's check result.

### Step 3: the harness forces handoffs

```python
if size > budget_chars and not warned:
    messages.append({"role": "user", "content": "Context nearly full: write a note for your next session, then stop."})
```

The model decides *what* to write; the harness decides *when*. Waiting for the model to notice its context is full doesn't work: it can't see its own context size.

### Step 4: a scripted model that only knows its context

The offline "model" is a deterministic policy. It plans from the todo list in its first message, reacts to tool results, and re-checks `in_progress` items first. It never reads the disk directly, so it's in the same position as a real model starting a fresh session. While writing it we hit a bug worth knowing: after finishing its last item, its plan list was empty, so it re-read the *original* todo list from its first message and kept re-checking and re-marking `mod_08` until the budget stopped it. The harness's budget turned an endless loop into one wasted session. The fix was to tell "not planned yet" apart from "nothing left".

### Step 5: run it

```text
session 1: handoff                                                 items done: 3  peak context:  6,665 chars
session 2: crash (process killed after editing src/mod_04.py)      items done: 0  peak context:      0 chars
session 3: handoff                                                 items done: 4  peak context:  6,656 chars
session 4: finished                                                items done: 1  peak context:  2,368 chars

result: 8/8 done, all verified: True, all files pass the check: True

PROGRESS.md:
# Progress

Goal: replace print() with logging in every module under src/.

- Session handoff: next up ['mod_04', 'mod_05', 'mod_06']. Pattern per file: add the logging header above the first def, then replace print( with log.info(.
- Session handoff: next up ['mod_08']. Pattern per file: add the logging header above the first def, then replace print( with log.info(.

same task in one unbounded session: peak context 12,671 chars
```

Session 2 died with `mod_04` edited but not marked done. Session 3 found it `in_progress`, ran the check first (it passed, since the edit had completed), marked it done, and moved on. Session 3 handed off partway through `mod_08`, and session 4 again checked first, found it incomplete, finished it, and verified it. The ~6,600-character peak per session is the budget plus the step that crossed it. It stays flat however many modules there are, while the single session's context grows with every module: 12,671 characters for 8 modules, and it would keep growing.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Practice | Where you'll see it |
|----------|---------------------|
| Progress files and todo lists | Coding agents' todo tools; `PROGRESS.md`/`NOTES.md` conventions in long agent runs |
| Fresh sessions from files | Running an agent in a loop where each iteration reads the plan and the repo, not the last transcript |
| Checkpoints | Git commits per item; Claude Code's checkpoints and `/rewind` |
| Compaction | Summarising the transcript in place (Phase 4 · Context compaction), the alternative to a full handoff |
| Durable execution | Workflow engines (Temporal, LangGraph checkpointers) for agents that must survive restarts |

Compaction and handoff solve the same problem differently. Compaction keeps one session going by summarising it. Handoff ends the session and starts clean from files. Handoff is more robust to crashes and drift, because the files are the source of truth, not a summary of a transcript.

## Ship It

`outputs/skill-long-horizon-harness.md` is a skill for setting up a long-running agent task: todo and progress files, item statuses, verification per item, a per-session context budget with forced handoffs, atomic writes, checkpoints, and a "re-check in_progress first" rule.

## Exercises

1. **Easy.** Set `budget_chars=2500`. How many sessions does the task take now? What's the cost of very small sessions?
2. **Medium.** Use `git` for checkpoints: commit after each verified item with the item id in the message, and implement rollback with `git checkout`.
3. **Medium.** Add a `blocked` status: if an item fails its check 3 times, mark it blocked with a note and move on instead of stopping the whole task.
4. **Hard.** Run 3 sessions in parallel on different items (Phase 8 · Parallel fan-out). What has to change in `todo.json` handling so two workers never take the same item?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Long-horizon task | "Big task" | Work that needs more steps than one context window or one process can hold |
| Handoff | "Start a new session" | Ending a session with a note and continuing from files in a fresh context |
| Progress file | "Notes to self" | A human-readable record of decisions and next steps that each session reads |
| Atomic write | "Safe save" | Write to a temp file then rename, so readers never see half a file |
| In-progress recovery | "Resume" | Treating interrupted items as unverified and checking them first |
| Checkpoint | "Restore point" | A saved copy of the state before an item, for rollback |

## Further Reading

- [Anthropic, Effective harnesses for long-running agents (2025)](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Anthropic, Effective context engineering for AI agents (2025)](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [METR, Measuring AI ability to complete long tasks (2025)](https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/)
- [Python docs: os.replace (atomic rename)](https://docs.python.org/3/library/os.html#os.replace)
- [Temporal: durable execution](https://docs.temporal.io/)
