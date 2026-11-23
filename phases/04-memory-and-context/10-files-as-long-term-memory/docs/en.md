# Files as Long-Term Memory

> The simplest memory that works across sessions is a folder of Markdown files the agent can read and edit. Make the tools safe, keep an index in every prompt, and the next session picks up where this one stopped.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 4 · Lessons 1 and 9; Phase 2 · Lessons 5 and 6
**Time:** ~40 minutes

## Learning Objectives

- Implement memory file tools (view, create, str_replace, insert, delete) scoped to one directory.
- Defend them: reject paths that escape the directory (including through symlinks), limit file types, cap file and directory size, and require edits to match exactly once.
- Load a short index file into every system prompt, so a new session knows what memory exists.
- Show two sessions with no shared context continuing the same task through files.

## The Problem

Lessons 5 to 8 built memory out of databases: vectors, facts, episodes. They work, and they are invisible. You can't open them in an editor, review them in a pull request, or fix a wrong fact by hand without writing code.

Meanwhile the most widely used agent memory in practice is a file. Claude Code reads `CLAUDE.md` at the start of every session. Codex and many other tools read `AGENTS.md` (this repository has one). Long-running agents keep a `progress.md` or a TODO list and re-read it after compaction (Lesson 9). Anthropic's memory tool gives Claude a `/memories` directory with file commands. Files are readable, diffable, editable by people and models alike, and every model already knows how to work with them.

Giving a model file tools is also how you give it a way to overwrite `~/.ssh/authorized_keys`. The tools must be designed for that.

## The Concept

### The layout

| File | Holds | Loaded |
|------|-------|--------|
| `MEMORY.md` | A short index: one line per file, what it holds | Into every system prompt, truncated |
| `progress.md` | The current task: done, in progress, next | When the agent views it |
| `decisions.md` | Decisions and why | When needed |
| Topic files | Anything else worth keeping | When needed |

The index is progressive disclosure again (Lesson 7): the model always sees what exists, and reads the details only when a task needs them.

### The tools

| Tool | Arguments | Rule |
|------|-----------|------|
| `view` | path | A directory lists files with sizes; a file shows numbered lines |
| `create` | path, text | Creates or overwrites; size checked first |
| `str_replace` | path, old, new | `old` must appear **exactly once** |
| `insert` | path, line, text | After line `line` (0 = top) |
| `delete` | path | Never the root |

`str_replace` with "exactly once" is the same design Claude Code and Anthropic's text editor tool use. It forces the model to quote enough context, and it makes an edit to the wrong place fail loudly instead of silently.

### The defences

| Threat | Defence |
|--------|---------|
| `../../etc/passwd`, `/etc/passwd` | Resolve the path, require it to be inside the root |
| A symlink inside the root pointing outside | Resolve *after* following links, then check |
| Writing scripts or binaries | Allow only `.md`, `.txt`, `.json` |
| Memory growing for ever | Per-file and total size caps, with an error that says what to do |
| Exceptions killing the loop | Every tool returns a string; errors are observations (Phase 2 · Lesson 5) |

## Build It

```bash
cd code
python3 main.py
```

```text
session 1:
  view(/memories) -> (empty)
  create(/memories/progress.md) -> ok: wrote progress.md (238 chars)
  create(/memories/decisions.md) -> ok: wrote decisions.md (95 chars)
  create(/memories/MEMORY.md) -> ok: wrote MEMORY.md (105 chars)
  final: Stopping for today. Progress is in /memories/progress.md.

files left behind:
  MEMORY.md  (105 chars)
  decisions.md  (95 chars)
  progress.md  (238 chars)

session 2 starts with a fresh context; its system prompt contains:

   (loaded automatically)
  # Memory index
  - progress.md: current task, what is done, what is next
  - decisions.md: decisions and why

session 2:
  view(/memories/progress.md) ->    1  # Date-parsing bug (import job)
  str_replace(/memories/progress.md) -> ok: edited progress.md
  str_replace(/memories/progress.md) -> error: the text to replace must appear exactly once; found 4 times. In
  view(../../etc/passwd) -> error: path escapes the memory directory: '../../etc/passwd'
  final: Resumed from memory: fixing dates.py:88 with date.fromisoformat next, then running the tests. progress.md is updated.
```

Both sessions are scripted, but session 2's second step is not fixed: `resume()` reads the `progress.md` the tool returned and acts on its "Next" section. Delete that line from session 1's file and session 2 asks what to work on instead. The two failures in session 2 are on purpose: a vague edit (`"- "` appears four times) and a path outside the directory. Both come back as error strings, and the loop carries on.

The demo ends by printing `progress.md`: the "Fix dates.py:88" item has moved from "Next" to "In progress (session 2)". Session 2 knew nothing about the bug except what session 1 wrote down.

### Step 1: `resolve()`

Strips an optional `/memories` prefix, rejects other absolute paths, joins with the root, and calls `Path.resolve()`, which follows symlinks and removes `..`. Then it checks that the result *is* the root or has the root among its parents. Checking the string for `..` instead would miss symlinks and odd encodings; resolve, then compare.

### Step 2: The tools

Each tool is a few lines. `check_size()` runs before every write, counting the file's new size and the directory's total (minus the old version of the file, so overwriting with something shorter always works). `call()` dispatches by name and turns `ValueError`, `TypeError` (missing arguments) and `OSError` into `error: ...` strings.

### Step 3: The index in the prompt

`index_text()` returns the first 40 lines of `MEMORY.md`, with a marker if there are more. The system prompt tells the agent to read what is relevant at the start, write progress before it stops, and keep the index short. That instruction is what makes the files useful. Without it, many models never look.

### Step 4: Try a real model in session 2

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

Session 1 is still scripted, so the files are the same. Session 2 is a real model with the five tool schemas and the index in its prompt. Watch whether it views `progress.md` before acting, whether its `str_replace` calls quote enough context to match once, and whether it updates the file before it stops. The memory directory is printed at the end so you can open the files yourself.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: four escaping paths, a symlink pointing out, file types, size caps (including overwrite), refusing to delete the root, exactly-once replacement, insert and line numbers, bad arguments as observations, index truncation, and two sessions resuming through files.

## Use It

| Tool | File memory |
|------|-------------|
| Claude Code | `CLAUDE.md` (project, user and local), loaded at session start; `#` to add a memory |
| Anthropic memory tool | A client-side `/memories` directory with `view`, `create`, `str_replace`, `insert`, `delete`, `rename`; you implement the storage |
| Codex, Cursor, others | `AGENTS.md` and rules files read at session start |
| Long-running agent harnesses | A progress file and git history as the hand-off between context windows |

## Ship It

`outputs/skill-file-memory.md` is a skill that gives an agent a safe memory directory: tool definitions, path and symlink checks, type and size limits, exactly-once edits, an index loaded into every prompt, and a two-session resume test.

## Exercises

1. **Easy.** Add `rename(old_path, new_path)`. Which checks does it need on *both* paths?
2. **Medium.** Make every write append a line to `/memories/.log` (time, tool, path), and make that file read-only to the model. How do you stop `create` overwriting it?
3. **Medium.** Session 1 writes 30 files. Make `MEMORY.md` update itself: after each write, regenerate it from the first heading of every file. What does the model lose compared with writing the index itself?
4. **Hard.** Run two agents on the same memory directory at once. Construct a sequence where one agent's `str_replace` silently discards the other's write. Add a version check (like `if_version` in a database) to prevent it.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| File memory | "CLAUDE.md", "notes" | Markdown files the agent reads and edits with tools, persisting between sessions |
| Memory index | "Table of contents" | A short file, loaded into every prompt, saying what each memory file holds |
| Path traversal | "../ attack" | Using `..`, absolute paths or symlinks to reach files outside the allowed directory |
| Exactly-once edit | "str_replace" | An edit that fails unless the text to replace appears exactly one time |
| Progress file | "Handoff file" | A file recording done, in progress and next, so a fresh context can continue |

## Further Reading

- [Anthropic, Memory tool (docs)](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/memory-tool)
- [Anthropic, Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Claude Code, Manage Claude's memory](https://docs.anthropic.com/en/docs/claude-code/memory)
- [AGENTS.md](https://agents.md/)
- [OWASP, Path Traversal](https://owasp.org/www-community/attacks/Path_Traversal)
