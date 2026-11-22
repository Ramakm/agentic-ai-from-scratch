# Project Layout for Agent Repos

> A demo agent fits in one file. A real one has config, prompts, tools, tests, evals and traces, and if they don't each have a home on day one, they end up everywhere.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 0 · Lessons 1–7
**Time:** ~30 minutes

## Learning Objectives

- Lay out an agent repository so that config, model access, tools, prompts, tests, evals and traces each have one obvious home.
- Separate fast offline **tests** (does the code work?) from **evals** (does the agent behave?), and know why both are needed.
- Generate the layout with a scaffolder, and prove the generated project works by running its tests, CLI and evals.
- Write an `AGENTS.md` so coding agents working in your repo follow the same rules you do.

## The Problem

Every agent starts as `agent.py`. A month later, that file:

- reads `os.environ` in nine places, each with a different default model,
- has the system prompt as an f-string in the middle of a function, edited by three people,
- builds tool schemas by hand next to the HTTP client,
- has no tests, because every code path calls a paid API,
- and "works on my machine" with no record of what the agent did when it didn't.

None of this is hard to fix early, and all of it is painful to fix late. This lesson fixes it with structure, then makes the structure reproducible with a scaffolder.

## The Concept

### One home per concern

```text
my-agent/
├── agent/
│   ├── config.py        settings from env/.env — the only file that reads os.environ
│   ├── llm.py           the only module that talks to a model (real or scripted)
│   ├── loop.py          think → act → observe, step budget, transcript traces
│   ├── tools/           one tool per file, registered with @tool
│   └── prompts/         prompts as files, versioned and reviewed like code
├── tests/               fast, offline unit tests (scripted model)
├── evals/               golden tasks that measure behavior
├── traces/              run records (git-ignored)
├── .env.example         variable names only; the real .env is git-ignored
├── AGENTS.md            rules for coding agents working in this repo
└── pyproject.toml
```

| Rule | Why |
|------|-----|
| Only `config.py` reads the environment | One place to see every setting and its default; keys are masked in `repr` |
| Only `llm.py` talks to a model | Swapping providers, adding retries (Lesson 04) or tracing (Lesson 07) is a one-file change |
| Prompts are files | Diffs show prompt changes; reviews catch them; evals can compare versions |
| One tool per file | Tools are the agent's API surface. Each gets its own docstring, schema, tests |
| `tests/` never hits a network | Runs in CI on every push, free and deterministic |
| `evals/` may hit a real model | Measures behavior; runs on demand, before releases, and after prompt changes |

### Tests versus evals

| | Tests | Evals |
|--|-------|-------|
| Question | Does the code do what I wrote? | Does the agent do what users need? |
| Model | Scripted fake | Real model |
| Result | Pass/fail, deterministic | A score that varies between runs |
| When | Every commit | Before releases, after prompt or model changes |

You need both. A loop with a broken step budget fails a *test*. A model that answers arithmetic from memory instead of using the calculator fails an *eval*.

## Build It

```bash
cd code
python3 main.py new my-agent
cd my-agent
python3 -m agent "what is 6 * 7?"
python3 -m unittest discover -s tests
python3 evals/run_evals.py
```

### Step 1: Templates and the scaffolder

`main.py` holds every generated file as a template, with `__NAME__` as the only placeholder. `scaffold()` validates the name, refuses to write into a non-empty directory without `--force`, and writes 17 files.

### Step 2: The generated agent runs immediately

With no `AGENT_BASE_URL`, the CLI uses a scripted model, so a new project works with zero setup:

```text
Config(base_url='', model='llama3.2', api_key=<none>, max_steps=8)

  act     -> calculator({"expression": "6 * 7"})
  observe <- 42

[final_answer after 2 step(s); trace saved in traces/]
```

Every run also writes its full transcript to `traces/run-<timestamp>.json`, the simplest trace there is. Swap in Lesson 07's tracer when you need spans.

### Step 3: Tests and evals

Offline, the five unit tests pass and the evals score 3/3. That proves the *plumbing*. Then point the evals at a real model:

```bash
AGENT_BASE_URL=http://localhost:11434/v1 python3 evals/run_evals.py
```

From the two runs against `llama3.2` while writing this lesson:

```text
run 1:  FAIL what is 6 * 7?   PASS what is (2 + 3) ** 2?   FAIL what is 100 / 8?    → 1/3
run 2:  FAIL what is 6 * 7?                                PASS what is 100 / 8?
        answer for 6 * 7: {"name": "Evaluate", "parameters": {"expression": "6 * 7"}}
```

Three lessons in two runs:

1. **The model invented a tool** (`Evaluate`) and wrote the call as text, the same failure from Phase 3 · Lesson 1, now caught by an eval instead of a user.
2. **Scores vary between runs.** "100 / 8" failed, then passed. One eval run is an anecdote; run each case several times and report a pass rate.
3. **The tests still passed.** The code was fine. Only the eval could see the behavior problem. That's why both exist.

### Step 4: The scaffolder's own tests

```bash
python3 -m unittest -v test_main
```

They generate a project into a temp directory, compile every generated `.py` file, run the generated project's tests, CLI and evals in a subprocess, and check `.gitignore`. While building this lesson, these tests caught a generated `__main__.py` with a syntax error: an escaped quote inside a template turned into `""""`. A scaffolder whose output isn't executed in its tests will ship broken projects.

## Use It

- **cookiecutter** and **copier** are template-based scaffolders. Copier can also *update* existing projects when the template changes.
- **uv init** creates a minimal Python project (`pyproject.toml`, `.python-version`) you can drop this layout into.
- **`AGENTS.md`** is read by Codex, Cursor, Claude Code (alongside `CLAUDE.md`) and other coding agents. It's the cheapest way to keep generated changes consistent with your conventions.
- Frameworks impose their own layouts (LangGraph's `langgraph.json`, CrewAI's `config/agents.yaml`). The same concerns are underneath; map them onto these homes.

## Ship It

`outputs/skill-agent-repo-audit.md` is a skill that audits an existing agent repository against this layout. It finds scattered env reads, inline prompts, hand-built schemas, network-dependent tests, missing evals and committed traces, and proposes a step-by-step restructuring.

## Exercises

1. **Easy.** Add a second tool, `get_time`, as its own file in `agent/tools/`. What's the only other line you have to change?
2. **Medium.** Make `evals/run_evals.py` run each case 5 times and report a pass rate per case. Run it against `llama3.2`.
3. **Medium.** Add a `--template minimal` option to the scaffolder that generates only `agent/`, `tests/` and `.gitignore`.
4. **Hard.** Replace the transcript traces in `loop.py` with Lesson 07's tracer, and Lesson 05's `LLM` class in `llm.py` so the project speaks both the OpenAI and Anthropic formats. Keep the generated tests passing.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Scaffolder | "Project template" | A tool that generates a working project skeleton from templates |
| Test | "Unit test" | A deterministic, offline check that code does what it was written to do |
| Eval | "Benchmark" | A run of real tasks against a real model, scored, to measure behavior |
| Golden task | "Test case" | An input with a known good outcome, used in evals |
| `AGENTS.md` | "Agent instructions" | A repo file that tells coding agents the project's rules and commands |

## Further Reading

- [AGENTS.md, a simple open format for guiding coding agents](https://agents.md/)
- [Python Packaging User Guide, Writing your pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Copier documentation](https://copier.readthedocs.io/)
- [Anthropic, *Building Effective Agents*: start simple, add complexity only when it helps](https://www.anthropic.com/research/building-effective-agents)
