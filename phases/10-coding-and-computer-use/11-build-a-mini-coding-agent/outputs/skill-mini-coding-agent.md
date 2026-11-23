---
name: mini-coding-agent
description: >
  Run the course's mini coding agent on a real Python repository and judge the result:
  prepare AGENTS.md, pick a model, run on a working copy, read the status, transcript
  and diff, and decide whether to apply it. Use when someone wants to try the Phase 10
  agent on their own code, or asks how to evaluate a single coding-agent run.
---

# Run the mini coding agent on a repo

## 1. Prepare
- Make sure `python -m unittest` (or the repo's test command) runs from the repo root.
  If the repo uses pytest, adapt `TEST_RUNNER` or add a thin unittest wrapper first.
- Add a short `AGENTS.md`: what the project is, how to run tests, layout, rules.
- Choose a model with solid tool calling. Small local models (≈3B) rarely complete
  multi-step edits; 7B+ coding models or hosted models do much better.

## 2. Run
```bash
AGENT_BASE_URL=... AGENT_MODEL=... python3 main.py --repo path/to/repo "Fix the failing tests in X"
```
The agent edits a temporary copy. Read-only shell commands run; anything else asks.

## 3. Judge
| Status | Do |
|--------|----|
| verified | Read the diff. Is it minimal? Does it fix the cause, not the symptom? Apply with `git apply`. |
| unverified | The model stopped without passing tests after its last edit. Don't trust the answer text. |
| stuck | Read the last failures in the transcript; give the agent a hint or narrow the task. |
| tampered | Discard the run. Tighten instructions; consider denying shell writes. |
| budget | Raise `--max-steps` only if the transcript shows steady progress. |

## 4. Record
Keep the transcript (`transcript-*.jsonl`) with the decision. These runs become your
first evaluation dataset in Phase 11.
