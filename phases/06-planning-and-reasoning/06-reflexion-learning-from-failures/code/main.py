"""Reflexion: try, get an external verdict, write down the lesson, and try again with every lesson so far.

The task: implement parse_duration("1h30m") -> 5400. Unit tests are the evaluator. Three strategies:
  once          one attempt
  retry         retry with the latest test failure only
  reflexion     after each failure, write a one-line reflection; the next attempt sees all of them
Candidate code runs in a separate Python process with a timeout, never inside this one.

    python3 main.py             # offline: a stand-in coder that handles exactly the cases it has been told about
    python3 main.py --live      # AGENT_MODEL writes the code and the reflections
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from typing import Callable

SPEC = ('Write a Python function parse_duration(text: str) -> int that converts durations like "45s", "2h", '
        '"1h30m" or "1h 30m" to seconds. Raise ValueError for empty or invalid input.')
TESTS = [   # (name, input, expected: an int, or "ValueError")
    ("seconds", "45s", 45), ("hours", "2h", 7200), ("hours and minutes", "1h30m", 5400),
    ("minutes only", "90m", 5400), ("space between parts", "1h 30m", 5400),
    ("empty string", "", "ValueError"), ("garbage", "abc", "ValueError"),
]

HARNESS = """
import json, sys
sys.setrecursionlimit(200)
ns = {}
exec(open(sys.argv[1]).read(), ns)
results = {}
for name, arg, want in json.loads(sys.argv[2]):
    try:
        got = ns["parse_duration"](arg)
        results[name] = "pass" if want != "ValueError" and got == want else f"returned {got!r}, expected {want!r}"
    except ValueError:
        results[name] = "pass" if want == "ValueError" else f"raised ValueError, expected {want!r}"
    except Exception as e:
        results[name] = f"raised {type(e).__name__}: {e}"
print(json.dumps(results))
"""


def evaluate(code: str, timeout: float = 5.0) -> dict[str, str]:
    """Run the candidate in a fresh, isolated interpreter (-I) with a timeout. Phase 10 adds a real sandbox;
    this is the minimum: never exec generated code in your own process."""
    with tempfile.TemporaryDirectory() as tmp:
        src, harness = os.path.join(tmp, "candidate.py"), os.path.join(tmp, "harness.py")
        open(src, "w").write(code)
        open(harness, "w").write(HARNESS)
        try:
            out = subprocess.run([sys.executable, "-I", harness, src, json.dumps(TESTS)], cwd=tmp,
                                 capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {name: "timed out" for name, _, _ in TESTS}
        if out.returncode != 0:
            return {name: f"crashed: {out.stderr.strip().splitlines()[-1] if out.stderr else 'no output'}"
                    for name, _, _ in TESTS}
        return json.loads(out.stdout)

# ---------------------------------------------------------------- the offline coder

LESSON_FOR = {   # which feature fixes which failing test
    "minutes only": "minutes", "hours and minutes": "minutes", "space between parts": "spaces",
    "empty string": "validate", "garbage": "validate",
}


def write_code(features: set[str]) -> str:
    """Stand-in coder: it writes a parser that handles exactly the cases it knows to handle. 'Knowing'
    comes only from the feedback it is shown, which is the variable this lesson is about."""
    units = "{'h': 3600, 'm': 60, 's': 1}" if "minutes" in features else "{'h': 3600, 's': 1}"
    lines = ["import re", "", "def parse_duration(text):"]
    if "spaces" in features:
        lines.append("    text = text.replace(' ', '')")
    lines.append(f"    units = {units}")
    lines.append(f"    parts = re.findall(r'(\\d+)([{''.join(sorted('hms' if 'minutes' in features else 'hs'))}])', text)")
    if "validate" in features:
        lines.append("    if not parts or ''.join(n + u for n, u in parts) != text:")
        lines.append("        raise ValueError(f'invalid duration: {text!r}')")
    lines.append("    return sum(int(n) * units[u] for n, u in parts)")
    return "\n".join(lines) + "\n"


def reflect_offline(failures: dict[str, str]) -> str:
    """Stand-in reflection. Like most real reflections, it names one thing: the first failing test."""
    name, detail = next(iter(failures.items()))
    return f"Test '{name}' failed ({detail}); next time handle {LESSON_FOR.get(name, 'that case')}."


def features_from(texts: list[str]) -> set[str]:
    return {f for f in ("minutes", "spaces", "validate") for t in texts if f in t}

# ---------------------------------------------------------------- strategies


def run(strategy: str, max_attempts: int = 4, coder: Callable | None = None, reflect: Callable | None = None) -> dict:
    reflections: list[str] = []
    last_feedback = ""
    history = []
    for attempt in range(1, max_attempts + 1):
        if coder:
            code = coder(reflections if strategy == "reflexion" else [last_feedback] if last_feedback else [])
        else:
            known = reflections if strategy == "reflexion" else [last_feedback]
            code = write_code(features_from(known))
        results = evaluate(code)
        failures = {k: v for k, v in results.items() if v != "pass"}
        history.append(len(results) - len(failures))
        if not failures or strategy == "once":
            break
        lesson = (reflect or reflect_offline)(failures)
        if strategy == "reflexion":
            reflections.append(lesson)
        last_feedback = lesson               # retry sees only the newest lesson
    return {"passed_per_attempt": history, "solved": not failures, "attempts": len(history),
            "reflections": reflections}

# ---------------------------------------------------------------- live


def chat(prompt: str) -> str:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)["choices"][0]["message"]["content"] or ""


def live_coder(lessons: list[str]) -> str:
    prompt = SPEC + ("\n\nLessons from earlier attempts:\n" + "\n".join(f"- {l}" for l in lessons) if lessons else "")
    text = chat(prompt + "\n\nReply with only the Python code in one ```python block.")
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return m.group(1) if m else text


def live_reflect(failures: dict[str, str]) -> str:
    report = "\n".join(f"- {k}: {v}" for k, v in failures.items())
    return chat(f"{SPEC}\n\nYour code failed these tests:\n{report}\n\nIn one sentence, what should you do "
                "differently next time? Be specific.").strip()


if __name__ == "__main__":
    live = "--live" in sys.argv
    print(f"{len(TESTS)} tests; candidate code runs in a separate interpreter\n")
    for strategy in ("once", "retry", "reflexion"):
        r = run(strategy, coder=live_coder if live else None, reflect=live_reflect if live else None)
        print(f"{strategy:9} tests passed per attempt: {' -> '.join(f'{p}/{len(TESTS)}' for p in r['passed_per_attempt'])}"
              f"   solved={r['solved']}")
        for line in r["reflections"]:
            print(f"{'':10}reflection: {line}")
