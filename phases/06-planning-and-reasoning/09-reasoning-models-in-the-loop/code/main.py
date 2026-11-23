"""Reasoning models in the loop: spend slow, expensive thinking only on the steps that need it.

An agent run has many easy steps (format a tool call, summarise a result) and a few hard ones (plan,
verify, resolve a conflict). Four policies decide which model handles each step:
  all fast        a fast model everywhere
  all reasoning   a reasoning model everywhere
  by role         reasoning model for planner and verifier steps, fast model for the rest
  escalate        fast model first; if a checker rejects its output, retry with the reasoning model

Offline numbers come from MODEL PROFILES THAT ARE ILLUSTRATIVE ASSUMPTIONS (prices, latencies and
success rates I chose), not measurements. They show how the policies trade off; plug in your own.
--live measures a real fast model and a real reasoning model on checkable tasks.

    python3 main.py
    python3 main.py --live      # needs AGENT_MODEL and AGENT_REASONING_MODEL
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass

# ---------------------------------------------------------------- assumptions (replace with your own)


@dataclass
class Profile:
    name: str
    usd_per_1k_out: float          # output tokens, including hidden reasoning tokens
    tokens_per_step: dict          # output tokens per step, by difficulty
    seconds_per_step: dict
    success: dict                  # probability the step's output passes its checker, by difficulty


FAST = Profile("fast", 0.002, {"easy": 150, "hard": 300}, {"easy": 1.0, "hard": 2.0}, {"easy": 0.97, "hard": 0.55})
REASONING = Profile("reasoning", 0.010, {"easy": 900, "hard": 4000}, {"easy": 6.0, "hard": 25.0},
                    {"easy": 0.98, "hard": 0.90})

CHECKER_CATCHES = 0.8    # assumed: the checker detects 80% of bad outputs (escalation only helps on those)

# One agent run: (role, difficulty). Most steps are easy; planning and verification are hard.
RUN = ([("planner", "hard")] + [("tool_call", "easy")] * 12 + [("summarise", "easy")] * 4
       + [("verifier", "hard"), ("conflict", "hard")])


def step_cost(p: Profile, difficulty: str) -> tuple[float, float, float]:
    """(dollars, seconds, success probability) for one attempt."""
    return (p.tokens_per_step[difficulty] / 1000 * p.usd_per_1k_out, p.seconds_per_step[difficulty],
            p.success[difficulty])


def policy(name: str, role: str, difficulty: str) -> tuple[float, float, float]:
    """Expected dollars, seconds and success for one step under a policy."""
    if name == "all fast":
        return step_cost(FAST, difficulty)
    if name == "all reasoning":
        return step_cost(REASONING, difficulty)
    if name == "by role":
        return step_cost(REASONING if role in ("planner", "verifier") else FAST, difficulty)
    # escalate: fast first; if its output is bad AND the checker notices, pay for a reasoning attempt too
    fd, fs, fp = step_cost(FAST, difficulty)
    rd, rs, rp = step_cost(REASONING, difficulty)
    caught = (1 - fp) * CHECKER_CATCHES
    return fd + caught * rd, fs + caught * rs, fp + caught * rp


def evaluate(name: str) -> dict:
    dollars = seconds = 0.0
    success = 1.0
    for role, difficulty in RUN:
        d, s, p = policy(name, role, difficulty)
        dollars, seconds, success = dollars + d, seconds + s, success * p
    return {"usd": dollars, "seconds": seconds, "success": success}

# ---------------------------------------------------------------- live measurement

LIVE_TASKS = [   # (prompt, checker) — small but checkable
    ("What is 17 * 23? Reply with the number only.", lambda a: "391" in a),
    ("A train leaves at 08:47 and the trip takes 2 h 38 min. What time does it arrive? Reply HH:MM only.",
     lambda a: "11:25" in a),
    ("Ana is older than Ben. Ben is older than Chen. Dee is younger than Chen. Who is the second youngest? "
     "Reply with the name only.", lambda a: "chen" in a.lower()),
    ("How many letters 'r' are in the word 'strawberry'? Reply with the number only.", lambda a: re.search(r"\b3\b", a)),
]


def measure(model: str) -> dict:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    right, seconds, tokens = 0, 0.0, 0
    for prompt, check in LIVE_TASKS:
        body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.load(resp)
        seconds += time.perf_counter() - t0
        tokens += data.get("usage", {}).get("completion_tokens", 0)
        right += bool(check(data["choices"][0]["message"]["content"] or ""))
    return {"right": right, "seconds": seconds, "completion_tokens": tokens}


if __name__ == "__main__":
    if "--live" in sys.argv:
        for env in ("AGENT_MODEL", "AGENT_REASONING_MODEL"):
            model = os.environ.get(env, "llama3.2" if env == "AGENT_MODEL" else "qwen3")
            r = measure(model)
            print(f"{env:22} {model:20} right {r['right']}/{len(LIVE_TASKS)}  {r['seconds']:6.1f} s  "
                  f"{r['completion_tokens']} completion tokens")
        sys.exit()
    hard = sum(d == "hard" for _, d in RUN)
    print(f"one run: {len(RUN)} steps ({hard} hard).  ASSUMED profiles: fast succeeds {FAST.success}, "
          f"reasoning succeeds {REASONING.success},\n"
          f"checker catches {CHECKER_CATCHES:.0%} of bad outputs\n")
    print(f"{'policy':14} {'cost per run':>13} {'seconds per run':>16} {'run succeeds':>13}")
    for name in ("all fast", "all reasoning", "by role", "escalate"):
        r = evaluate(name)
        print(f"{name:14} {'$' + format(r['usd'], '.4f'):>13} {r['seconds']:>16.1f} {r['success']:>13.1%}")
