# Your Agent Dev Environment

> Agents fail in ways that look like model problems but are really setup problems. Check your machine once, properly, and you'll stop debugging the wrong thing.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** None
**Time:** ~45 minutes

## Learning Objectives

- Set up an environment where every lesson in this course runs: Python, a virtual environment, git, and optionally Node.
- Run a model locally with Ollama, or connect a hosted API, and know which one each lesson uses.
- Handle API keys so they never land in your code, your git history, or your terminal output.
- Build `agent-doctor`, a script that checks all of the above and tells you exactly what to fix.

## The Problem

Your first agent will fail. When it does, you need to know whether the fault is in your loop, the model, or your machine. "Connection refused" might mean Ollama isn't running. A tool call that does nothing might mean you pulled an embedding model instead of a chat model. A 401 means your key isn't exported in *this* shell. A `SyntaxError` on `int | str` means you're on Python 3.9.

None of these are agent problems, but each can eat an hour. This lesson removes them once, and leaves you with a script that catches them every time you set up a new machine.

## The Concept

### What this course needs

| Tool | Why | Required? |
|------|-----|-----------|
| Python 3.10+ | Every lesson's `code/main.py`; 3.10 adds `X \| Y` type unions | Yes |
| A virtual env | Keeps each project's packages separate | Strongly recommended |
| git | Cloning the course, versioning your agents | Yes |
| Node 20+ | TypeScript versions of lessons, MCP tooling | Optional |
| A model | Local (Ollama) **or** hosted (an API key) | At least one |

Most lessons use only the Python standard library. When a lesson needs a package, it says so at the top.

### Local vs hosted models

| | Local (Ollama) | Hosted (OpenAI, Anthropic, …) |
|--|----------------|-------------------------------|
| Cost | Free after download | Pay per token |
| Privacy | Nothing leaves your machine | Prompts go to the provider |
| Capability | Good for learning; small models make more tool-calling mistakes | Strongest models; most reliable tool use |
| Setup | `ollama pull llama3.2` | Create a key, export it |

The course works with either. Small local models are *useful* for learning because they fail visibly: you'll see malformed tool calls you'd rarely see from a frontier model, and your loop has to handle them.

Every lesson talks to models through the **OpenAI-compatible** `/chat/completions` format, which Ollama, OpenAI, vLLM, LM Studio and many others accept. Switching providers means changing a base URL, not rewriting code.

### Keys are secrets

- Put keys in environment variables (`export OPENAI_API_KEY=…`), or in a `.env` file that is listed in `.gitignore`.
- Never hard-code a key, paste it into a notebook cell, or print it. Even in debug output, print *which* keys exist, never their values.
- If a key ever reaches a git commit, rotate it. Deleting the commit isn't enough.

## Build It

### Step 1: Python and a virtual environment

```bash
python3 --version            # needs 3.10 or newer
mkdir agents && cd agents
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
```

### Step 2: A model

Local:

```bash
# install from https://ollama.com, then:
ollama pull llama3.2         # a 3B chat model with tool-calling support (~2 GB)
ollama run llama3.2 "Say hi" # quick smoke test
```

Or hosted:

```bash
export OPENAI_API_KEY=...    # or ANTHROPIC_API_KEY, GEMINI_API_KEY, ...
```

### Step 3: Run agent-doctor

```bash
git clone https://github.com/Ramakm/agentic-ai-from-scratch.git
cd agentic-ai-from-scratch/phases/00-setup-and-tooling/01-your-agent-dev-environment/code
python3 main.py --ping
```

```text
agent-doctor

[ok]   Python       3.13.7
[warn] Virtual env  not active
                   fix: python3 -m venv .venv && source .venv/bin/activate
[ok]   git          git version 2.46.0
[ok]   node         v24.9.0
[ok]   Ollama       3 model(s): nomic-embed-text:latest, moondream:latest, llama3.2:latest
[warn] API keys     none set
                   fix: Optional. Export e.g. OPENAI_API_KEY or ANTHROPIC_API_KEY, or use Ollama locally

ping llama3.2:latest -> 'agent ready'

Ready. Next lesson: Python & TypeScript for agents.
```

The exit code is `0` when you're ready and `1` when you're not, so you can use it in scripts and CI.

### Step 4: Read how it works

Open `code/main.py`. Each check is a small function that returns a `Check(name, status, detail, fix)`:

- `check_python` and `check_venv` compare `sys.version_info`, and `sys.prefix` against `sys.base_prefix`.
- `check_binary` uses `shutil.which` and runs `--version`.
- `check_ollama` calls `GET /api/tags` on the Ollama server. Any failure means "not reachable", which is a warning, not a crash.
- `check_keys` reports only the *names* of keys that are set. There's a test that proves the value never appears in the output.
- `chat_models` drops embedding models and ranks known text-chat families first. Without it, `--ping` once chose `nomic-embed-text` (which can't chat), and then `moondream` (a vision model that returned an empty reply). Both are real bugs from building this lesson.

Every check takes its inputs as parameters with real defaults (`which=shutil.which`, `fetch=fetch_json`), so the tests can pass in fakes without mocking libraries:

```bash
python3 -m unittest -v test_main
```

## Use It

In real projects you'll pair this with:

- **uv** (`uv venv`, `uv pip install`), a much faster drop-in for venv and pip.
- **direnv** or **python-dotenv**, which load `.env` per project so keys never live in your shell profile.
- **pre-commit** with a secret scanner like `gitleaks`, which blocks commits that contain keys.
- **LiteLLM** or **OpenRouter**, one OpenAI-compatible endpoint in front of many providers.

## Ship It

`outputs/skill-agent-doctor.md` is a skill your coding agent can load to diagnose a broken agent setup. It runs the same checks, reads the output, and walks you through each fix.

## Exercises

1. **Easy.** Add a check for free disk space (models are big). Warn below 10 GB using `shutil.disk_usage`.
2. **Medium.** Add a `--json` flag that prints the checks as JSON, so other tools (or an agent) can read the result.
3. **Medium.** Add a hosted-API ping: if `OPENAI_API_KEY` is set, send one tiny request and report the latency. Make sure a 401 becomes a clear `fail` with a fix, not a traceback.
4. **Hard.** Check whether the chosen local model supports tool calling. Send one request with a trivial tool and report whether the reply contains `tool_calls`. Run it against two different models.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Virtual environment | "venv" | A per-project Python install with its own packages |
| Ollama | "Local LLM" | A server that downloads and runs open models, with an OpenAI-compatible API |
| OpenAI-compatible | "Works like OpenAI" | Accepts the `/chat/completions` request format, so one client works everywhere |
| Embedding model | "The other model" | Turns text into vectors for search; it cannot hold a conversation |
| Secret | "API key" | A credential that must live in the environment, never in code or logs |

## Further Reading

- [Python docs, `venv`](https://docs.python.org/3/library/venv.html)
- [Ollama, OpenAI compatibility](https://github.com/ollama/ollama/blob/main/docs/openai.md)
- [uv, Python package and project manager](https://docs.astral.sh/uv/)
- [GitHub, Removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
