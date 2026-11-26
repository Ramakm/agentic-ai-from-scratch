"""Human-in-the-loop design: decide when a person adds information, not just when an action is scary.
Compare three policies over a day of agent actions on prompts asked and harmful actions caught, under
a simple model of reviewer fatigue. Then make approvals durable: pause the agent, persist the request,
resume hours later, and re-check the world before acting.

    python3 main.py

Standard library only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

# ---------------------------------------------------------------- actions in a working day


@dataclass(frozen=True)
class Action:
    kind: str
    target: str
    risk: str                # "low" | "medium" | "high"
    reversible: bool
    harmful: bool = False    # ground truth for the simulation only; the policy can't see it


def day() -> list[Action]:
    """40 actions from a coding-and-ops agent. Three are harmful: two came from an injection, one is a mistake."""
    acts = []
    for i in range(40):
        kind, risk, rev = [("read_file", "low", True), ("run_tests", "low", True), ("edit_file", "medium", True),
                           ("search", "low", True), ("send_email", "medium", False)][i % 5]
        acts.append(Action(kind, f"{kind}-{i}" if kind != "send_email" else "team@corp.example", risk, rev))
    acts[12] = Action("pay_invoice", "INV-77 to usual IBAN", "high", False)                       # expected, legit
    acts[25] = Action("pay_invoice", "INV-91 to NEW IBAN", "high", False, harmful=True)            # injected
    acts[31] = Action("edit_file", "tests/test_payments.py (delete 40 lines)", "medium", True, harmful=True)  # mistake
    acts[37] = Action("post_public", "gist with config.yml", "high", False, harmful=True)          # injected
    return acts

# ---------------------------------------------------------------- policies


def ask_everything(a: Action, plan: set) -> bool:
    return True


def ask_by_tier(a: Action, plan: set) -> bool:
    return a.risk == "high" or (a.risk == "medium" and not a.reversible)


def plan_then_exceptions(a: Action, plan: set) -> bool:
    """The human approves a plan once. Then ask only for high-risk irreversible actions and anything
    outside the plan (a new kind of action, or an edit to a file the plan didn't mention)."""
    if a.risk == "high" and not a.reversible:
        return True
    key = a.kind if a.kind != "edit_file" else f"edit:{a.target.split(' ')[0]}"
    return key not in plan


def approved_plan(acts: list[Action]) -> set:
    """What the agent proposed up front: the kinds of work, and which source files it will edit."""
    return {"read_file", "run_tests", "search", "send_email"} | {f"edit:{a.target}" for a in acts
                                                                  if a.kind == "edit_file" and not a.harmful}


def attention(k: int) -> float:
    """ASSUMPTION, not data: chance the reviewer notices a bad action on their k-th prompt of the day.
    Starts high and decays as prompts pile up. Change it and see how the ranking holds."""
    return max(0.3, 0.95 - 0.025 * (k - 1))


def simulate(policy, acts: list[Action], plan_review: bool = False) -> dict:
    plan = approved_plan(acts) if plan_review else set()
    k = 1 if plan_review else 0                     # reviewing the plan counts as one prompt
    caught = 0.0
    unasked_harm = []
    for a in acts:
        if policy(a, plan):
            k += 1
            if a.harmful:
                caught += attention(k)
        elif a.harmful:
            unasked_harm.append(a.target)
    return {"prompts": k, "expected_caught": caught, "unasked_harm": unasked_harm}

# ---------------------------------------------------------------- durable approvals


@dataclass
class Pending:
    id: str
    action: dict
    precondition: str            # hash of the facts the human approved against
    created_at: float
    expires_at: float
    agent_state: dict            # enough to resume the run: messages, step, plan


def fingerprint(facts: dict) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()[:12]


def request_approval(action: dict, facts: dict, agent_state: dict, now: float, ttl_h: float = 24) -> str:
    """Pause: serialise everything needed to continue, then the process can exit."""
    p = Pending(fingerprint(action), action, fingerprint(facts), now, now + ttl_h * 3600, agent_state)
    return json.dumps(asdict(p))


def resume(saved: str, decision: str, current_facts: dict, now: float) -> tuple[str, str]:
    """Hours later, maybe in another process. Returns (outcome, reason)."""
    p = Pending(**json.loads(saved))
    if now > p.expires_at:
        return "denied", "approval expired; default is no"
    if decision != "approve":
        return "denied", "human said no"
    if fingerprint(current_facts) != p.precondition:
        return "re-ask", "the facts changed since approval; show the new card"
    return "execute", f"resume at step {p.agent_state['step']}"


if __name__ == "__main__":
    acts = day()
    print("assumption: reviewer attention on the k-th prompt =", ", ".join(f"k={k}: {attention(k):.2f}" for k in (1, 10, 20, 30, 40)))
    print(f"\n{'policy':<26}{'prompts':>8}{'harmful caught':>16}   harmful actions never shown to a human")
    for name, pol, pr in (("ask everything", ask_everything, False), ("ask by risk tier", ask_by_tier, False),
                          ("plan + exceptions", plan_then_exceptions, True)):
        r = simulate(pol, acts, pr)
        print(f"{name:<26}{r['prompts']:>8}{r['expected_caught']:>11.2f} / 3   {', '.join(r['unasked_harm']) or '-'}")

    print("\ndurable approval:")
    t0 = 1_700_000_000.0
    action = {"tool": "pay_invoice", "invoice": "INV-77", "iban": "DE89 3704 0044 0532 0130 00", "amount": 1200}
    facts = {"invoice_amount": 1200, "iban_on_file": "DE89 3704 0044 0532 0130 00"}
    saved = request_approval(action, facts, {"step": 7, "messages": ["..."]}, t0)
    print("  paused, saved", len(saved), "bytes; process can exit")
    print("  approve 2h later, facts unchanged:  ", resume(saved, "approve", facts, t0 + 2 * 3600))
    print("  approve 2h later, IBAN changed:     ", resume(saved, "approve", {**facts, "iban_on_file": "GB33 BUKB 2020 1555 5555 55"}, t0 + 2 * 3600))
    print("  approve 30h later:                  ", resume(saved, "approve", facts, t0 + 30 * 3600))
    print("  deny:                               ", resume(saved, "deny", facts, t0 + 60))
