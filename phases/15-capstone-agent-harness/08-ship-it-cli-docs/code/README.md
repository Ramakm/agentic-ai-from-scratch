# harness

An agent harness you built yourself: a coding agent for your own repos, in about 2,000 lines of standard-library Python, docstrings included. Built across Phase 15 of [Agentic AI from Scratch](https://github.com/Ramakm/agentic-ai-from-scratch).

```text
harness run "the restock test fails; fix it" --verify "python3 -m unittest"
```

- **Core loop and tool registry.** Schema-checked tool calls. Errors come back to the model as observations, and the loop stops on steps, budget, or repeated calls.
- **Context manager.** It clips old tool output, then compacts old turns into a summary, so long tasks fit in the context window.
- **Memory.** Notes survive between sessions, and each note records where it came from.
- **MCP client.** It uses any stdio MCP server's tools, without passing your environment to the server.
- **Subagents.** A `task` tool runs read-only explorers in a fresh context. They share the token budget and can't start more subagents.
- **Permissions.** Each tool call is allowed, asked about, or denied by rule. Plan mode runs only read-only tools.
- **Sandboxed shell.** Commands run in the workspace with a scrubbed environment, a timeout and resource limits.
- **Verification.** After the agent says it's done, the harness runs your check command itself and sends failures back to the agent.
- **Traces and evals.** Every run writes a JSONL trace, and an eval runner checks what the agent *did*, not only what it said.

## Install

Python 3.10+, no dependencies.

```bash
pip install -e .            # or: uv pip install -e .   -> gives you the `harness` command
python3 -m harness --help   # works without installing, from this folder
```

Point it at a model through any OpenAI-compatible endpoint:

```bash
export AGENT_BASE_URL=http://localhost:11434/v1  AGENT_MODEL=llama3.2       # Ollama
export AGENT_BASE_URL=https://api.openai.com/v1  AGENT_MODEL=gpt-4o-mini  AGENT_API_KEY=...
```

Small local models are good for learning the harness and poor at real tasks. See [What to expect](#what-to-expect).

## Commands

| Command | What it does |
|---------|--------------|
| `harness init` | Writes `.harness.json` and `HARNESS.md` into the workspace, and adds `.harness/` to `.gitignore` |
| `harness run "task"` | Runs one task and asks before side effects. `--verify CMD` checks the work |
| `harness chat` | A conversation; each line continues the same session |
| `harness tools` | Lists every tool, whether it writes, and what the rules decide for it |
| `harness eval tasks.json` | Runs an eval suite in throwaway workspaces. `--save-baseline` / `--baseline` catch regressions |
| `harness trace FILE` | Shows a trace as a tree, with subagents nested under their parent |

Flags for `run`, `chat`, `tools` and `eval`: `--root DIR` (default `.`), `--mode default|plan|auto`, `--no-mcp`. `run` and `chat` also take `--max-steps` and `--verify`.

## Configuration

`.harness.json` in the workspace root, merged over the defaults:

```json
{
  "mode": "default",
  "verify": "python3 -m unittest",
  "permissions": {
    "allow": ["bash(make test*)", "edit_file(src/*)"],
    "ask":   ["mcp__notes__add_note"],
    "deny":  ["bash(docker*)"]
  },
  "mcpServers": {
    "notes": {"command": "python3", "args": ["servers/notes_server.py"], "env": {}}
  },
  "context": {"budget_tokens": 12000, "keep_recent": 8},
  "max_steps": 30,
  "budget_tokens": 300000
}
```

- **Your permission rules are added to the defaults.** The defaults deny `.env` files, `rm -rf`, `sudo`, `git push`, `curl`/`wget` and edits to `.git/` and `.harness/`, and allow read-only git and test commands. Run `harness tools` to see the full list. To start from nothing, set `"replaceDefaultRules": true`.
- **How rules are matched.** Order: deny, then the mode, then ask, then allow, then the default. With no rule, read-only tools run and everything else asks. `auto` mode runs it instead, but deny and ask rules still apply.
- **Rule syntax.** `tool` or `tool(glob)`. The glob is matched against the tool's main argument: `path` for file tools, `command` for `bash`. A compound command (`a && b`) is allowed only if every part matches an allow rule. A command containing `$(...)` or backticks is never allowed by rule.
- **MCP servers** get only `PATH`, `HOME` and the locale variables, plus whatever you list in `env`. Their `readOnlyHint` is ignored unless you set `"trustReadOnlyHints": true` for that server.
- **Model settings never go in the config file.** They come from the environment, so keys stay out of the repo.
- **`HARNESS.md`** (or `AGENTS.md`, or `CLAUDE.md`) in the workspace root is added to the system prompt.

## Files it writes

| Path | What |
|------|------|
| `.harness/traces/*.jsonl` | One trace per run: model calls, tool calls (secrets redacted), subagents, stop reason |
| `.harness/memory.json` | Notes saved with `remember`, with source and date |

## Writing evals

```json
[{"id": "fix-restock",
  "prompt": "tests/test_stock.py has a failing test. Fix the code, not the test.",
  "files": {"inventory/stock.py": "...", "tests/test_stock.py": "..."},
  "checks": [{"type": "command_passes", "command": "python3 -m unittest"},
             {"type": "file_unchanged", "path": "tests/test_stock.py"},
             {"type": "tool_called", "tool": "bash", "args_contain": {"command": "unittest"}}],
  "script": [{"calls": [["read_file", {"path": "inventory/stock.py"}]]}, {"say": "Fixed."}]}]
```

Check types:
- `answer_contains`, `answer_not_contains`
- `file_contains`, `file_unchanged`, `command_passes` (runs a command in the workspace afterwards; exit code 0 passes)
- `tool_called`, `tool_not_called`
- `stop_reason`, `max_steps`, `max_tokens`

`script` makes a task run offline in CI. With `AGENT_BASE_URL` set, the eval runner uses the real model instead.

## What to expect

On the demo workspace, llama3.2 (3B) searched twice and invented a bug that isn't in the code. It never edited a file and said the tests passed. `--verify` caught it: the test command failed three times, and the run exited with code 1 instead of reporting success.

That's the harness doing its job. The harness can stop a model from doing damage and from lying about the result. It can't make the model good at the task. Use a model with reliable tool calling for real work, and keep `--verify` on.

## Layout

```text
harness/
  llm.py           model interface: scripted model, OpenAI-compatible client, token estimate
  tools.py         Tool, ToolRegistry: schemas, validation, errors as observations, output clipping
  hooks.py         Hook, RunState, Usage, Budget, StopRun
  loop.py          Agent.run: the loop (unchanged since 15.02)
  builtin_tools.py workspace file tools with a path jail
  context.py       ContextManager hook, Memory, project instructions
  mcp.py           MCP stdio client and tool adapter
  subagents.py     Delegator: the `task` tool and profiles
  permissions.py   rules, modes, approvers
  sandbox.py       the bash tool's limited process
  trace.py         Tracer hook, trace viewer
  evals.py         eval tasks, checks, runner, baseline comparison
  app.py           config, assembly, verification
  cli.py           the `harness` command
servers/notes_server.py   a demo MCP server
sample_project/           a tiny module with one failing test
evals/tasks.json          an eval suite for sample_project
```

## Limits

- **The sandbox isn't a security boundary.** Commands can read anything your user can read, and they can reach the network. Run untrusted work in a container (Phase 12, lesson 5).
- **Tool calls run one at a time,** including several subagents asked for in the same turn.
- **Token counts are estimates** (about 4 characters per token) unless the provider reports usage.
- **No streaming output.** The CLI prints each step as it finishes.

MIT licensed.
