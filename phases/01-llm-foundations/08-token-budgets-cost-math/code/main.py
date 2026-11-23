"""Token budgets & cost math: what a call costs, what an agent run costs, what caching saves,
and how long it takes, from measured prefill and decode speeds.

All prices here are EXAMPLE rates for the arithmetic. Use your provider's current price page.

    python3 main.py            # cost math: one call, an agent run, caching, a month
    python3 main.py --live     # measure llama3.2's prefill and decode speed, fit a latency model, test it
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from dataclasses import dataclass

# ---------------------------------------------------------------- prices


@dataclass(frozen=True)
class Price:
    """USD per million tokens. cached_input: price of input read from the provider's prompt cache."""
    input: float
    output: float
    cached_input: float | None = None

    def cost(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
        cached_rate = self.input if self.cached_input is None else self.cached_input
        fresh = input_tokens - cached_tokens
        return (fresh * self.input + cached_tokens * cached_rate + output_tokens * self.output) / 1_000_000


EXAMPLE = {                                  # placeholders, not anyone's real prices
    "small": Price(input=0.25, output=1.25, cached_input=0.025),
    "large": Price(input=3.00, output=15.00, cached_input=0.30),
}

# ---------------------------------------------------------------- an agent run


@dataclass
class RunShape:
    steps: int = 8
    system: int = 1200          # system prompt tokens
    tools: int = 1500           # tool definitions
    task: int = 150             # the user's request
    per_step_in: int = 600      # what each step adds to the history (reply + tool result)
    per_step_out: int = 120     # tokens the model writes per step


def run_tokens(s: RunShape) -> list[tuple[int, int, int]]:
    """Per step: (input tokens, output tokens, input tokens that a prefix cache could reuse)."""
    rows, history = [], 0
    for step in range(s.steps):
        inp = s.system + s.tools + s.task + history
        cacheable = s.system + s.tools + s.task + history if step > 0 else 0   # everything sent last time
        rows.append((inp, s.per_step_out, cacheable))
        history += s.per_step_in
    return rows


def run_cost(s: RunShape, price: Price, caching: bool) -> float:
    return sum(price.cost(i, o, c if caching else 0) for i, o, c in run_tokens(s))


def monthly(cost_per_run: float, runs_per_day: int, days: int = 30) -> float:
    return cost_per_run * runs_per_day * days

# ---------------------------------------------------------------- latency


@dataclass
class Speed:
    prefill_tps: float          # input tokens processed per second
    decode_tps: float           # output tokens generated per second
    overhead_s: float = 0.0     # fixed per-request cost

    def latency(self, input_tokens: int, output_tokens: int) -> float:
        return self.overhead_s + input_tokens / self.prefill_tps + output_tokens / self.decode_tps


def fit_speed(samples: list[dict]) -> Speed:
    """Ollama reports token counts and nanosecond durations for each phase separately."""
    pin = sum(s["prompt_eval_count"] for s in samples)
    pdur = sum(s["prompt_eval_duration"] for s in samples) / 1e9
    dout = sum(s["eval_count"] for s in samples)
    ddur = sum(s["eval_duration"] for s in samples) / 1e9
    over = sum((s["total_duration"] - s["prompt_eval_duration"] - s["eval_duration"]) for s in samples) / 1e9 / len(samples)
    return Speed(pin / pdur, dout / ddur, over)


def max_tokens_for(deadline_s: float, input_tokens: int, speed: Speed) -> int:
    """The largest max_tokens that still finishes before the deadline."""
    left = deadline_s - speed.overhead_s - input_tokens / speed.prefill_tps
    return max(0, int(left * speed.decode_tps))

# ---------------------------------------------------------------- live measurement


def generate(prompt: str, num_predict: int) -> dict:
    base = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "prompt": prompt, "stream": False,
            "options": {"temperature": 0, "num_predict": num_predict, "num_ctx": 8192}}
    req = urllib.request.Request(base + "/api/generate", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.load(resp)


def filler(n_words: int, salt: str) -> str:
    """Distinct text each time, so the server's prompt cache can't skip the prefill."""
    words = "agent loop tool model token budget context memory step result".split()
    return f"[{salt}] " + " ".join(words[(i * 7) % len(words)] for i in range(n_words)) + "\nSummarise in one paragraph."


def live() -> None:
    samples = []
    print(f"{'input':>6} {'output':>6} {'prefill s':>9} {'decode s':>8} {'total s':>7}")
    for i, words in enumerate((50, 400, 1200, 2400)):
        r = generate(filler(words, f"s{i}"), 96)
        samples.append(r)
        print(f"{r['prompt_eval_count']:6} {r['eval_count']:6} {r['prompt_eval_duration'] / 1e9:9.2f} "
              f"{r['eval_duration'] / 1e9:8.2f} {r['total_duration'] / 1e9:7.2f}")
    speed = fit_speed(samples)
    print(f"\nfitted: prefill {speed.prefill_tps:.0f} tok/s, decode {speed.decode_tps:.1f} tok/s, "
          f"overhead {speed.overhead_s:.2f} s")
    r = generate(filler(1800, "check"), 200)
    predicted = speed.latency(r["prompt_eval_count"], r["eval_count"])
    print(f"new request: {r['prompt_eval_count']} in / {r['eval_count']} out -> predicted {predicted:.2f} s, "
          f"measured {r['total_duration'] / 1e9:.2f} s")
    for deadline in (5, 15, 30):
        print(f"max_tokens that fits a {deadline:2} s deadline after a 3,000-token prompt: "
              f"{max_tokens_for(deadline, 3000, speed)}")


if __name__ == "__main__":
    if "--live" in sys.argv:
        live()
        sys.exit()
    p = EXAMPLE["large"]
    print(f"one call, 2,000 in / 500 out, 'large' example rates: ${p.cost(2000, 500):.4f}"
          f"  (output is {500 * p.output / (2000 * p.input + 500 * p.output):.0%} of it)")
    shape = RunShape()
    rows = run_tokens(shape)
    print(f"\nan {shape.steps}-step agent run: input per step {[i for i, _, _ in rows]}")
    print(f"  total input {sum(i for i, _, _ in rows):,} tokens, output {sum(o for _, o, _ in rows):,}")
    for name, price in EXAMPLE.items():
        plain, cached = run_cost(shape, price, False), run_cost(shape, price, True)
        print(f"  {name:5}: ${plain:.4f} per run, ${cached:.4f} with prefix caching ({1 - cached / plain:.0%} less); "
              f"1,000 runs/day for 30 days: ${monthly(plain, 1000):,.0f} vs ${monthly(cached, 1000):,.0f}")
    for steps in (4, 8, 16, 32):
        print(f"  {steps:2} steps: ${run_cost(RunShape(steps=steps), p, False):.3f} per run (large, no caching)")
