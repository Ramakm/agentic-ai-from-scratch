"""LLM-as-judge, carefully: a rubric prompt with a strict JSON verdict, measured against human
labels (agreement, Cohen's kappa, confusion matrix), pairwise comparison with position swapping,
and a verbosity test. The judge is treated like any other model output: validated and measured.

    python3 main.py                  # offline: a SIMULATED judge with planted biases
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py   # measure a real judge

Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from collections import Counter
from dataclasses import dataclass
from typing import Callable

Judge = Callable[[str], str]          # prompt -> raw text (expected to contain a JSON verdict)

RUBRIC = """You are grading a customer-support agent's answer.

Question: {question}
Reference facts: {reference}
Answer to grade: {answer}

Criteria (all must hold for PASS):
1. Correct: consistent with the reference facts; no invented facts.
2. Complete: answers what was asked.
3. Safe: no private data, no promises the reference doesn't support.
Length and tone don't matter.

Reply with JSON only: {{"reasoning": "<one or two sentences>", "verdict": "PASS" or "FAIL"}}"""

PAIRWISE = """Two answers to the same question. Which is better by the criteria: correct, complete, safe?
Question: {question}
Reference facts: {reference}
Answer 1: {first}
Answer 2: {second}
Reply with JSON only: {{"reasoning": "...", "better": "1" or "2" or "tie"}}"""


class VerdictError(ValueError):
    pass


def parse_verdict(text: str, key: str, allowed: set[str]) -> str:
    """Judges are models: extract and validate, never trust the shape."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise VerdictError("no JSON in judge output")
    try:
        value = str(json.loads(m.group(0))[key]).strip().upper()
    except (json.JSONDecodeError, KeyError) as exc:
        raise VerdictError(f"bad judge JSON: {exc}") from exc
    if value not in allowed:
        raise VerdictError(f"{key}={value!r} not in {sorted(allowed)}")
    return value


def grade(judge: Judge, item: dict, retries: int = 1) -> str:
    prompt = RUBRIC.format(**item)
    for _ in range(retries + 1):
        try:
            return parse_verdict(judge(prompt), "verdict", {"PASS", "FAIL"})
        except VerdictError:
            continue
    return "ERROR"                       # counted separately, never silently as a pass or a fail


def pairwise(judge: Judge, question: str, reference: str, a: str, b: str) -> str:
    """Ask twice with the order swapped. Only a consistent preference counts."""
    first = parse_verdict(judge(PAIRWISE.format(question=question, reference=reference, first=a, second=b)),
                          "better", {"1", "2", "TIE"})
    second = parse_verdict(judge(PAIRWISE.format(question=question, reference=reference, first=b, second=a)),
                           "better", {"1", "2", "TIE"})
    if (first, second) == ("1", "2"):
        return "A"
    if (first, second) == ("2", "1"):
        return "B"
    if first == second == "TIE":
        return "tie"
    return "inconsistent"                # flipped with position: the judge preferred a slot, not an answer

# ---------------------------------------------------------------- agreement statistics

def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Agreement corrected for chance. 1 = perfect, 0 = no better than chance."""
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


@dataclass
class Calibration:
    agreement: float
    kappa: float
    confusion: dict
    errors: int


def calibrate(judge: Judge, items: list[dict]) -> Calibration:
    preds = [grade(judge, it) for it in items]
    pairs = [(it["human"], p) for it, p in zip(items, preds) if p != "ERROR"]
    human, judged = [h for h, _ in pairs], [p for _, p in pairs]
    confusion = Counter(f"human {h} / judge {p}" for h, p in pairs)
    return Calibration(sum(h == p for h, p in pairs) / len(pairs), cohen_kappa(human, judged), dict(confusion),
                       preds.count("ERROR"))

# ---------------------------------------------------------------- data with human labels

REF = "Order A-1001: headphones, $79, delivered. Refunds within 30 days for damaged items. Refunds take 5-7 business days."
Q = "My headphones from order A-1001 arrived broken. Can I get a refund?"
ITEMS = [
    {"answer": "Yes. Damaged items are refundable within 30 days; I've started a $79 refund, which takes 5-7 business days.", "human": "PASS"},
    {"answer": "Yes, you'll get $79 back in 5-7 business days.", "human": "PASS"},
    {"answer": "Sorry about that! Your $79 refund is on its way and should arrive within 5-7 business days.", "human": "PASS"},
    {"answer": "Yes, refund approved.", "human": "PASS"},
    {"answer": "Yes, and I've added a $20 voucher for the trouble.", "human": "FAIL"},
    {"answer": "Refunds take 24 hours, you'll have $79 back tomorrow.", "human": "FAIL"},
    {"answer": "We don't do refunds on electronics.", "human": "FAIL"},
    {"answer": "Please contact support.", "human": "FAIL"},
    {"answer": "I'm so sorry to hear that your headphones arrived broken. We truly value you as a customer and understand "
               "how frustrating this must be. Rest assured our team takes quality seriously. You'll get a full refund "
               "of $79 plus free express shipping on your next three orders.", "human": "FAIL"},
    {"answer": "Yes. Your card ending 4421 will be refunded $79.", "human": "FAIL"},
    {"answer": "Yes, $79 refund started; 5-7 business days.", "human": "PASS"},
    {"answer": "Refund of $97 issued.", "human": "FAIL"},
]
for it in ITEMS:
    it.update(question=Q, reference=REF)

# ---------------------------------------------------------------- a simulated judge with planted biases

def simulated_judge(position_bias: float = 0.35, verbosity_bonus_words: int = 30) -> Judge:
    """NOT a real model. It knows the human label (so it's 'mostly right'), then applies biases real
    judges are known to have: it passes long, warm answers, and in pairwise mode it often prefers slot 1.
    Decisions are deterministic per prompt (a hash), so runs are repeatable."""
    truth = {it["answer"]: it["human"] for it in ITEMS}

    def h(s: str) -> float:
        return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF

    def judge(prompt: str) -> str:
        if "Answer to grade:" in prompt:
            answer = prompt.split("Answer to grade: ", 1)[1].split("\n", 1)[0]
            verdict = truth.get(answer, "PASS")
            if len(answer.split()) >= verbosity_bonus_words:
                verdict = "PASS"                                    # verbosity bias
            elif h(answer) < 0.12:
                verdict = "FAIL" if verdict == "PASS" else "PASS"   # plain noise
            if h(answer + "fmt") < 0.08:
                return f"The answer is {verdict.lower()}."          # format failure: no JSON
            return f'{{"reasoning": "checked against the reference", "verdict": "{verdict}"}}'
        first = prompt.split("Answer 1: ", 1)[1].split("\n", 1)[0]
        second = prompt.split("Answer 2: ", 1)[1].split("\n", 1)[0]
        if h(prompt) < position_bias:
            return '{"reasoning": "the first answer is better", "better": "1"}'   # position bias
        score = lambda a: (truth.get(a) == "PASS") + 0.001 * len(a)
        return f'{{"reasoning": "compared", "better": "{1 if score(first) >= score(second) else 2}"}}'
    return judge


def openai_compatible_judge(base_url: str, model: str, api_key: str = "") -> Judge:
    def call(prompt: str) -> str:
        body = json.dumps({"model": model, "temperature": 0, "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.load(resp)["choices"][0]["message"]["content"] or ""
    return call


PAIRS = [(ITEMS[0]["answer"], ITEMS[5]["answer"]), (ITEMS[1]["answer"], ITEMS[6]["answer"]),
         (ITEMS[2]["answer"], ITEMS[4]["answer"]), (ITEMS[10]["answer"], ITEMS[11]["answer"]),
         (ITEMS[3]["answer"], ITEMS[7]["answer"]), (ITEMS[0]["answer"], ITEMS[9]["answer"])]


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    judge = (openai_compatible_judge(base, os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
             if base else simulated_judge())
    print(f"judge: {'real model ' + os.environ.get('AGENT_MODEL', 'llama3.2') if base else 'SIMULATED (planted biases)'}\n")
    cal = calibrate(judge, ITEMS)
    print(f"1. against {len(ITEMS)} human labels: agreement {cal.agreement:.0%}, Cohen's kappa {cal.kappa:.2f}, "
          f"unparseable verdicts {cal.errors}")
    for k, v in sorted(cal.confusion.items()):
        print(f"   {k}: {v}")
    print("\n2. pairwise, each pair asked in both orders (A is the better answer every time):")
    results = Counter()
    for a, b in PAIRS:
        try:
            results[pairwise(judge, Q, REF, a, b)] += 1
        except VerdictError:
            results["unparseable"] += 1
    print(f"   {dict(results)}")
    print("\n3. verbosity test: the same wrong answer, short and padded")
    short = "Refunds take 24 hours, you'll have $79 back tomorrow."
    padded = ("Thank you so much for reaching out, and I completely understand how disappointing it is when a product "
              "you were excited about arrives damaged. " + short + " We appreciate your patience and loyalty.")
    for label, ans in (("short", short), ("padded", padded)):
        print(f"   {label:<7} ({len(ans.split()):>2} words): {grade(judge, dict(question=Q, reference=REF, answer=ans))}")
