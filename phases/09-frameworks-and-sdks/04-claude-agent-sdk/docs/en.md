# Claude Agent SDK

> The Claude Agent SDK doesn't give you a loop to configure; it gives you a whole harness. Claude Code's loop, file tools, shell, context management and permission system run as a subprocess, and your program streams messages from it. Your job moves from writing the loop to deciding what the agent may do: allow rules, permission modes, hooks and a permission callback.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only; optional `with_claude_agent_sdk.py` needs `claude-agent-sdk` and Claude Code)
**Prerequisites:** Phase 9 · The same loop, ten frameworks; Phase 2 · Human approval gates; Phase 7 · Build an MCP server from scratch
**Time:** ~50 minutes

## Learning Objectives

- Explain what changes when the framework is a full harness rather than a loop library.
- Implement layered permissions: hooks, deny and allow rules, permission modes and a `can_use_tool` callback.
- Add an in-process custom tool exposed as `mcp__<server>__<tool>`.
- Stream a run as typed messages (`system` init, `assistant`, `user` tool results, `result`) and resume a session by id.

## The Problem

You want an agent that edits a repository: read files, change them, run commands. Phase 10 builds those tools from scratch, and there's a lot to get right: path jails, unique-match edits, shell timeouts, context compaction for long sessions, and above all **permission to act**. One bad `rm -rf` and the demo becomes an incident.

The Claude Agent SDK takes the other route. It ships the same harness that runs Claude Code: built-in `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash` and more, plus sessions and compaction. You don't write the loop. What you must write is the policy: which tools run freely, which need a human, which commands are never allowed.

## The Concept

**A harness, not a loop library.** Your program calls `query(prompt, options)` and receives a stream of messages. The SDK starts the Claude Code CLI and talks to it over stdin/stdout. Tools run inside that process, in the working directory you pass as `cwd`.

| Message | When | Carries |
|---------|------|---------|
| `system` (subtype `init`) | First | session id, available tools, MCP servers |
| `assistant` | Each model turn | text blocks and `tool_use` blocks |
| `user` | After tools run | `tool_result` blocks, including denials |
| `result` | Last | `success` or an error subtype, turn count, cost, session id |

**Permissions are layered.** Every tool call goes through several checks before it runs. In this lesson's version:

| Order | Layer | Example | Can do |
|-------|-------|---------|--------|
| 1 | `PreToolUse` hook | block `rm -rf` in `Bash` | deny (or rewrite input) |
| 2 | `disallowed_tools` | `["WebFetch"]` | deny |
| 3 | `allowed_tools` | `["Read", "Glob", "Grep"]` | allow without asking |
| 4 | `permission_mode` | `acceptEdits`, `plan`, `bypassPermissions` | allow edits, allow nothing but reads, allow all |
| 5 | `can_use_tool` callback | ask a human in your UI | allow or deny |

The real SDK follows the same idea, with hooks first, deny before allow, and the callback last. Its docs list the exact order for each version, and it warns (`CanUseToolShadowedWarning`) when a rule means your callback will never be asked.

**Custom tools** are MCP tools. `@tool` plus `create_sdk_mcp_server` runs an MCP server inside your Python process, with no subprocess. The agent sees each tool as `mcp__<server>__<tool>`, and that full name is what you put in `allowed_tools`.

## Build It

```bash
cd code
python3 main.py
```

The demo creates a temporary workspace with a `README.md` and a `build/` directory, then asks the agent to bump the version, count words and "clean build/ too".

### Step 1: built-in tools in a jail

```python
def path(self, p):
    full = (self.root / p).resolve()
    if full != self.root and self.root not in full.parents:
        raise PermissionError(f"{p!r} is outside the workspace")
    return full
```

`Edit` refuses unless `old_string` matches exactly once. That is how Claude Code's `Edit` tool behaves, and Phase 10 · Lesson 2 explains why.

### Step 2: decide, layer by layer

```python
def decide(options, name, args):
    denied = run_hooks(options, "PreToolUse", {"tool_name": name, "tool_input": args})
    if denied: return False, ..., "PreToolUse hook"
    if name in options.disallowed_tools: return False, ..., "disallowed_tools"
    if name in options.allowed_tools: return True, "", "allowed_tools"
    # permission_mode, then can_use_tool, else deny
```

The result also records *which layer decided*. Put that in your logs: "denied by hook" and "denied by user" need different fixes.

### Step 3: a custom tool

```python
@tool("word_count", "Count the words in a file in the workspace.", {"file_path": "string"})
def word_count(args):
    return {"content": [{"type": "text", "text": str(n)}], "is_error": n < 0}

mcp_servers={"docs": create_sdk_mcp_server("docs", [word_count])}
```

### Step 4: stream the run

```text
[init] session c4f723e6… tools: Read, Write, Edit, Glob, Grep, Bash, mcp__docs__word_count
[assistant] Let me find the README.
[tool_use] Glob {"pattern": "*.md"}
[result] (allowed_tools) README.md
[tool_use] Read {"file_path": "README.md"}
[result] (allowed_tools)    1	# Shop
[tool_use] Edit {"file_path": "README.md", "old_string": "version 1.0", "new_string": "version 1.1"}
[result] (can_use_tool) edited README.md
[tool_use] mcp__docs__word_count {"file_path": "README.md"}
[tool_use] Bash {"command": "rm -rf build"}
[result] (allowed_tools) 10
[result] (PreToolUse hook) ERROR Permission denied (PreToolUse hook): destructive command blocked: rm -rf build
[assistant] Bumped README to version 1.1 (10 words). I didn't delete build/: that was blocked.
[result] success after 5 turns

asked the human about: ['Edit']
README now: 'This is version 1.1 of the shop service.'
build/ still exists: True
```

Reads ran freely, the edit went to the human callback, the custom tool was pre-approved, and the hook stopped the destructive command. The denial came back to the model as a tool result, so it could explain itself instead of crashing.

### Step 5: resume a session

Every run ends with a `session_id`. Pass it back as `Options(resume=sid)` and the next query starts with the full earlier history. The real SDK stores sessions on disk under Claude Code's config directory and also offers `fork_session` to branch from one.

### Step 6: the real SDK

`with_claude_agent_sdk.py` sets up the same policy on `claude-agent-sdk` 0.2.187: `ClaudeAgentOptions(allowed_tools=..., permission_mode="default", can_use_tool=..., hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[...])]}, mcp_servers={"docs": create_sdk_mcp_server(...)})`. A full run starts Claude Code and costs tokens, so it isn't part of this lesson's offline output. Its `--check` mode calls the pieces we wrote without a model:

```text
word_count: {'content': [{'type': 'text', 'text': '10'}]}
hook on 'rm -rf build': {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': 'destructive command blocked: rm -rf build'}}
hook on 'ls': {}
options built: ClaudeAgentOptions ['Read', 'Glob', 'Grep', 'mcp__docs__word_count']
```

Note the real hook's shape: a `PreToolUse` hook denies by returning `hookSpecificOutput` with `permissionDecision: "deny"` and a reason. An empty dict means "no opinion".

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Need | Claude Agent SDK |
|------|------------------|
| One-shot task | `query(prompt=..., options=...)` |
| Multi-turn conversation in one process | `ClaudeSDKClient` |
| Read-only exploration | `permission_mode="plan"` or `allowed_tools` with only read tools |
| Trusted automation in a sandbox | `permission_mode="acceptEdits"`, or `bypassPermissions` only inside a container |
| Block patterns | `PreToolUse` hooks |
| Audit every action | `PostToolUse` hooks |
| Ask a human | `can_use_tool` |
| Your own tools | `@tool` + `create_sdk_mcp_server`, or any external MCP server |
| Specialist subagents | `agents={...}` with `AgentDefinition` |
| Budgets | `max_turns`, `max_budget_usd` |

Pick it when your agent's job looks like Claude Code's: working in files and a shell with strong built-in tools. Pick a loop library (Lessons 3 and 8) when your tools are business APIs and you want full control of every model call.

## Ship It

`outputs/skill-claude-agent-sdk-permissions.md` is a skill for writing a permission policy for a Claude Agent SDK app: classify every tool as free, ask or never, choose a permission mode, write `PreToolUse` hooks for dangerous patterns, add a `PostToolUse` audit log, and test the policy without a model.

## Exercises

1. **Easy.** Add a `PostToolUse` hook that appends every tool call and result to `audit.jsonl`.
2. **Medium.** Make a `PreToolUse` hook *rewrite* input instead of denying: turn `rm -rf build` into `mv build build.trash`. What new risks does input rewriting create?
3. **Medium.** Run the demo with `permission_mode="plan"`. Which steps fail, and how should the model's prompt change for a plan-only run?
4. **Hard.** Using the real SDK and your own account, run `with_claude_agent_sdk.py` without `--check`. Compare the real message stream with ours: which message types and fields did we leave out?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Harness | "The agent" | Loop, tools, context management and permissions packaged as one runtime |
| Permission mode | "Auto-approve" | A run-wide default: ask, accept edits, plan only, or bypass |
| Hook | "Callback" | Your function run at a lifecycle event, such as before or after a tool |
| `can_use_tool` | "Approval prompt" | The callback asked when no rule or mode decided |
| SDK MCP server | "Custom tools" | An MCP server running inside your process, exposed as `mcp__server__tool` |
| Session | "Conversation" | A stored transcript you can resume or fork by id |

## Further Reading

- [Claude Agent SDK overview](https://docs.claude.com/en/api/agent-sdk/overview)
- [Agent SDK: handling permissions](https://docs.claude.com/en/api/agent-sdk/permissions)
- [Agent SDK: custom tools](https://docs.claude.com/en/api/agent-sdk/custom-tools)
- [Claude Code hooks reference](https://docs.claude.com/en/docs/claude-code/hooks)
- [Anthropic, Building agents with the Claude Agent SDK (2025)](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)
