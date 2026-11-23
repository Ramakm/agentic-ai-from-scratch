"""Context compaction: keep a long agent run going when its history no longer fits.

A 25-step debugging run fills the window with file contents and test output. Three ways to shrink it:
  1. clear old tool results   (no model call; replaces stale results with a one-line stub)
  2. handoff note             (one summarizer call; goal, actions, notes, then the recent steps verbatim)
  3. both, triggered automatically when the run crosses a threshold
Each is checked for size, validity (no orphaned tool results) and recall of facts the run still needs.

    python3 main.py             # offline: compare the strategies on a recorded run
    python3 main.py --live      # live: a real model writes the handoff note
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Callable

# ---------------------------------------------------------------- counting and validity (Lesson 2)


def tokens(m: dict) -> int:
    return len(json.dumps(m)) // 4 + 4


def total(messages: list[dict]) -> int:
    return sum(tokens(m) for m in messages)


def units(messages: list[dict]) -> list[list[dict]]:
    out: list[list[dict]] = []
    for m in messages:
        if m["role"] == "tool" and out and out[-1][0].get("tool_calls"):
            out[-1].append(m)
        else:
            out.append([m])
    return out


def valid(messages: list[dict]) -> bool:
    pending: set[str] = set()
    for m in messages:
        if m["role"] == "tool":
            if m["tool_call_id"] not in pending:
                return False
            pending.discard(m["tool_call_id"])
        elif pending:
            return False
        for c in m.get("tool_calls") or []:
            pending.add(c["id"])
    return not pending

# ---------------------------------------------------------------- a recorded run


def call(i: int, name: str, args: dict, result: str) -> list[dict]:
    cid = f"c{i}"
    return [{"role": "assistant", "content": "", "tool_calls": [
                {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
            {"role": "tool", "tool_call_id": cid, "content": result}]


def filler(name: str, lines: int) -> str:
    return "\n".join(f"{name}:{n}: ordinary code, nothing to see here, keep reading" for n in range(1, lines + 1))


TASK = "The nightly import job fails. Find the cause and tell me the fix, with the file and line."
NEEDED = {"db port": "5433", "failing line": "dates.py:88", "bad format": "%d/%m/%Y"}


def recorded_run() -> list[dict]:
    m: list[dict] = [{"role": "system", "content": "You are a debugging agent. Use tools; be precise."},
                     {"role": "user", "content": TASK}]
    m += call(1, "read_file", {"path": "config.yaml"},
              "db:\n  host: db.internal\n  port: 5433   # not the default 5432\n" + filler("config.yaml", 40))
    m += call(2, "run", {"cmd": "python import_job.py"},
              filler("log", 60) + "\nTraceback (most recent call last):\n  File \"dates.py\", line 88, in parse\n"
              "ValueError: time data '2026-11-03' does not match format '%d/%m/%Y'")
    m += call(3, "note", {"text": "Crash: dates.py:88 parses with '%d/%m/%Y' but data is ISO (2026-11-03)."}, "ok")
    for i, path in enumerate(["import_job.py", "models.py", "db.py", "utils.py", "settings.py", "cli.py",
                              "tests/test_dates.py", "README.md", "requirements.txt", "Makefile"], start=4):
        m += call(i, "read_file", {"path": path}, filler(path, 45))
    m += call(14, "read_file", {"path": "dates.py"},
              filler("dates.py", 87) + "\ndates.py:88:     return datetime.strptime(s, '%d/%m/%Y')\n"
              + filler("dates.py(after)", 20))
    for i in range(15, 20):
        m += call(i, "grep", {"pattern": "strptime", "path": f"pkg{i}"}, filler(f"pkg{i}", 25))
    m += call(20, "run", {"cmd": "pytest -q tests/test_dates.py"}, filler("pytest", 50) + "\n1 failed, 12 passed")
    return m

# ---------------------------------------------------------------- strategy 1: clear old tool results


def clear_tool_results(messages: list[dict], keep_last: int = 3) -> list[dict]:
    """Replace the content of all but the newest `keep_last` tool results with a stub. Calls stay, so
    the model can see what it did and re-run a tool if it needs the output again."""
    tool_idx = [i for i, m in enumerate(messages) if m["role"] == "tool"]
    old = set(tool_idx[:-keep_last] if keep_last else tool_idx)
    out, calls = [], {}
    for i, m in enumerate(messages):
        for c in m.get("tool_calls") or []:
            calls[c["id"]] = f"{c['function']['name']}({c['function']['arguments']})"
        if i in old and len(m["content"]) > 80:
            m = {**m, "content": f"[cleared: {calls[m['tool_call_id']]} returned {len(m['content'])} characters. "
                                  f"Call the tool again if you need it.]"}
        out.append(m)
    return out

# ---------------------------------------------------------------- strategy 2: handoff note

Summarizer = Callable[[list[dict]], str]


def offline_note(messages: list[dict]) -> str:
    """Deterministic stand-in for a model-written handoff note: the goal, one line per action with the
    first line of its result, and every note() the agent wrote. It reads only what is in the messages."""
    goal = next(m["content"] for m in messages if m["role"] == "user")
    actions, notes, results = [], [], {m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"}
    for m in messages:
        for c in m.get("tool_calls") or []:
            args = json.loads(c["function"]["arguments"])
            if c["function"]["name"] == "note":
                notes.append(args["text"])
            else:
                first = next((ln.strip() for ln in results.get(c["id"], "").splitlines() if ln.strip()), "")
                actions.append(f"- {c['function']['name']}({', '.join(map(str, args.values()))}): {first[:70]}")
    return ("## Handoff note (earlier steps were compacted)\n"
            f"Goal: {goal}\n\nDone so far:\n" + "\n".join(actions) +
            "\n\nNotes:\n" + ("\n".join(f"- {n}" for n in notes) or "- (none)"))


NOTE_PROMPT = ("You are compacting an agent's history. Write a handoff note for the agent that will continue.\n"
               "Include: the goal; what has been done; every specific value found (numbers, file:line, formats, "
               "names), copied exactly; what is still open. Under 250 words. No preamble.\n\nHistory:\n")


def llm_note(llm: Callable[[str], str]) -> Summarizer:
    def note(messages: list[dict]) -> str:
        lines = []
        for m in messages:
            if m.get("tool_calls"):
                lines += [f"CALL {c['function']['name']} {c['function']['arguments']}" for c in m["tool_calls"]]
            elif m["role"] in ("user", "tool", "assistant") and m.get("content"):
                lines.append(f"{m['role'].upper()}: {m['content']}")
        return "## Handoff note (earlier steps were compacted)\n" + llm(NOTE_PROMPT + "\n".join(lines)).strip()
    return note


def compact(messages: list[dict], summarize: Summarizer, keep_units: int = 3) -> list[dict]:
    """System + task stay. Everything between them and the newest `keep_units` units becomes one note."""
    us = units(messages)
    head, middle, tail = us[:2], us[2:-keep_units], us[-keep_units:]
    if not middle:
        return messages
    note = summarize([m for u in head + middle for m in u])
    return [m for u in head for m in u] + [{"role": "user", "content": note}] + [m for u in tail for m in u]

# ---------------------------------------------------------------- strategy 3: automatic, in the loop


def auto_compact(messages: list[dict], window: int, summarize: Summarizer, threshold: float = 0.7,
                 clear_first: bool = True) -> tuple[list[dict], list[str]]:
    """What a loop runs before each model call, once the history crosses `threshold` of the window.
    clear_first=True tries the free option first and summarises only if still too big."""
    steps: list[str] = []
    if total(messages) <= window * threshold:
        return messages, steps
    if clear_first:
        messages = clear_tool_results(messages)
        steps.append(f"cleared old tool results -> ~{total(messages)} tokens")
    if total(messages) > window * threshold:
        messages = compact(messages, summarize)
        steps.append(f"compacted with a handoff note -> ~{total(messages)} tokens")
    return messages, steps


def recall(messages: list[dict]) -> list[str]:
    text = " ".join(str(m.get("content") or "") for m in messages)
    return [k for k, v in NEEDED.items() if v in text]

# ---------------------------------------------------------------- main


def openai_compatible(base_url: str, model: str, api_key: str = "") -> Callable[[str], str]:
    def ask(prompt: str) -> str:
        body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.load(resp)["choices"][0]["message"]["content"] or ""
    return ask


WINDOW = 8000

if __name__ == "__main__":
    summarize: Summarizer = offline_note
    if "--live" in sys.argv:
        summarize = llm_note(openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                               os.environ.get("AGENT_MODEL", "llama3.2"),
                                               os.environ.get("AGENT_API_KEY", "")))
    run = recorded_run()
    rows = {
        "no compaction": run,
        "clear old tool results": clear_tool_results(run),
        "handoff note": compact(run, summarize),
        "clear, then note": compact(clear_tool_results(run), summarize),
    }
    print(f"recorded run: {len(run)} messages; window {WINDOW} tokens; needed later: {list(NEEDED)}\n")
    for label, msgs in rows.items():
        fits = "fits" if total(msgs) <= WINDOW else "OVER WINDOW"
        print(f"{label:24} {len(msgs):3} msgs  ~{total(msgs):5} tokens  {fits:11} valid={valid(msgs)}  "
              f"recall={recall(msgs)}")
    for clear_first in (True, False):
        msgs, steps = auto_compact(run, WINDOW, summarize, clear_first=clear_first)
        print(f"\nautomatic at 70% of the window, clear_first={clear_first}: {'; '.join(steps)}; "
              f"recall={recall(msgs)}")
    print(f"\nthe handoff note the next step sees:\n")
    print(next(m["content"] for m in compact(run, summarize) if m["content"].startswith("## Handoff")))
