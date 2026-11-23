"""Handoffs between agents: one conversation, several specialists, and control passing between
them with a transfer tool. What travels with the handoff decides what the next agent knows.

    python3 main.py

Each agent's "model" is a scripted policy: a few lines that decide what to say or which tool to
call from what that agent can see. That keeps the run deterministic and makes the point visible:
the policies are identical across runs; only the context each agent receives changes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------------
# Tools the specialists own
# --------------------------------------------------------------------------------------------

LEDGER = {"C-1042": [("2026-11-02", 49.0, "Pro plan"), ("2026-11-02", 49.0, "Pro plan")]}
REFUNDS: list[tuple[str, float]] = []


def find_duplicate_charge(customer_id: str) -> str:
    rows = LEDGER.get(customer_id, [])
    dupes = [r for r in rows if rows.count(r) > 1]
    return f"duplicate: {dupes[0][1]:.2f} on {dupes[0][0]}" if dupes else "no duplicates"


def refund(customer_id: str, amount: float) -> str:
    REFUNDS.append((customer_id, amount))
    return f"refunded {amount:.2f} to {customer_id}"


def check_crash_reports(customer_id: str, app_version: str) -> str:
    return "known crash in 4.2.0 on login; fixed in 4.2.1" if app_version == "4.2.0" else "no known crash"


# --------------------------------------------------------------------------------------------
# Conversation machinery
# --------------------------------------------------------------------------------------------


@dataclass
class Msg:
    role: str          # user | agent | tool | handoff
    who: str           # which agent (or "user")
    text: str


@dataclass
class Handoff:
    to: str
    reason: str
    summary: str
    payload: dict


@dataclass
class Convo:
    history: list[Msg] = field(default_factory=list)
    active: str = "triage"
    handoffs: list[tuple[str, str]] = field(default_factory=list)
    tokens_read: int = 0
    asked_user: int = 0
    specialist_tokens: int = 0


ALLOWED = {"triage": {"billing", "tech", "sales"}, "billing": {"tech", "triage"},
           "tech": {"billing", "triage"}, "sales": {"triage"}}
REQUIRED_PAYLOAD = {"customer_id", "issues", "done"}


def context_for(convo: Convo, policy: str, incoming: Handoff | None, since: int) -> list[Msg]:
    """What the active agent sees. This is the whole design decision of a handoff.
    After taking over, an agent always sees what happened since (its own tool results, user replies)."""
    if policy == "full" or incoming is None:
        return list(convo.history)
    if policy == "summary":
        head = [Msg("handoff", incoming.to, f"Summary from previous agent: {incoming.summary}")]
    else:
        head = [Msg("handoff", incoming.to, f"Handoff payload: {json.dumps(incoming.payload, sort_keys=True)}")]
    return head + convo.history[since:]


def visible_text(ctx: list[Msg]) -> str:
    return "\n".join(m.text for m in ctx)


# --------------------------------------------------------------------------------------------
# Scripted agent policies (stand-ins for each agent's model)
# --------------------------------------------------------------------------------------------

CUSTOMER = re.compile(r"\bC-\d+\b")
VERSION = re.compile(r"\b\d+\.\d+\.\d+\b")


def triage(ctx: list[Msg], convo: Convo) -> dict:
    text = visible_text(ctx).lower()
    issues = [i for i, words in {"billing": ("charged", "refund", "invoice"), "tech": ("crash", "error", "login"),
                                 "sales": ("upgrade", "pricing", "seats")}.items() if any(w in text for w in words)]
    cid = (CUSTOMER.findall(visible_text(ctx)) or [None])[0]
    if not issues:
        return {"say": "How can I help?"}
    return {"handoff": issues[0], "reason": f"customer reports {', '.join(issues)} issue(s)",
            "summary": f"Customer says they were charged twice and the app crashes." if len(issues) > 1
            else f"Customer has a {issues[0]} issue.",
            "payload": {"customer_id": cid, "issues": issues, "done": [],
                        "app_version": (VERSION.findall(visible_text(ctx)) or [None])[0]}}


def billing(ctx: list[Msg], convo: Convo) -> dict:
    text = visible_text(ctx)
    cid = (CUSTOMER.findall(text) or [None])[0]
    if cid is None:
        return {"ask": "Could you give me your customer ID? It starts with C-."}
    if "refunded" not in text:
        found = find_duplicate_charge(cid)
        if found.startswith("duplicate"):
            amount = float(found.split()[1])
            return {"tool": "refund", "args": {"customer_id": cid, "amount": amount}, "note": found}
    tech_open = "crash" in text.lower() or '"tech"' in text
    if tech_open and "fixed in" not in text:
        return {"handoff": "tech", "reason": "billing resolved; app crash remains",
                "summary": "Refunded the duplicate charge. The app still crashes.",
                "payload": {"customer_id": cid, "issues": ["tech"], "done": ["refunded duplicate 49.00"],
                            "app_version": (VERSION.findall(text) or [None])[0]}}
    return {"say": "Your duplicate charge has been refunded."}


def tech(ctx: list[Msg], convo: Convo) -> dict:
    text = visible_text(ctx)
    cid = (CUSTOMER.findall(text) or [None])[0]
    version = (VERSION.findall(text) or [None])[0]
    if cid is None:
        return {"ask": "Which customer ID is this for?"}
    if version is None:
        return {"ask": "Which app version are you on? (Settings > About)"}
    result = check_crash_reports(cid, version)
    refunded = "refunded" in text
    return {"say": f"{result.capitalize()}. Please update to 4.2.1." +
                   (" Your refund for the duplicate charge is already done." if refunded else "")}


AGENTS = {"triage": triage, "billing": billing, "tech": tech}


# --------------------------------------------------------------------------------------------
# The runner, with handoff guards
# --------------------------------------------------------------------------------------------


def run(user_turns: list[str], policy: str, agents: dict = AGENTS, user_answers: dict | None = None,
        log=print) -> Convo:
    REFUNDS.clear()
    convo = Convo()
    answers = dict(user_answers or {})
    incoming: Handoff | None = None
    since = 0
    for turn in user_turns:
        convo.history.append(Msg("user", "user", turn))
        for _ in range(12):  # steps per user turn
            ctx = context_for(convo, policy, incoming, since)
            convo.tokens_read += len(visible_text(ctx)) // 4
            if convo.active != "triage":
                convo.specialist_tokens += len(visible_text(ctx)) // 4
            action = agents[convo.active](ctx, convo)
            if "handoff" in action:
                to = action["handoff"]
                problem = handoff_problem(convo, to, action)
                if problem:
                    log(f"  [{convo.active}] handoff to {to} blocked: {problem}; escalating to a human")
                    convo.history.append(Msg("agent", convo.active, "Escalated to a human agent."))
                    return convo
                incoming = Handoff(to, action["reason"], action["summary"], action["payload"])
                convo.handoffs.append((convo.active, to))
                convo.history.append(Msg("handoff", convo.active, f"transfer_to_{to}: {action['reason']}"))
                log(f"  [{convo.active}] -> transfer_to_{to}({action['reason']!r})")
                convo.active, since = to, len(convo.history)
            elif "tool" in action:
                out = {"refund": refund}[action["tool"]](**action["args"])
                convo.history.append(Msg("tool", convo.active, f"{action['note']}; {out}"))
                log(f"  [{convo.active}] {action['tool']}({action['args']}) -> {out}")
            elif "ask" in action:
                convo.asked_user += 1
                reply = answers.get(action["ask"])
                log(f"  [{convo.active}] asks the user again: {action['ask']}" + (f"  -> {reply}" if reply else ""))
                convo.history.append(Msg("agent", convo.active, action["ask"]))
                if reply is None:
                    return convo
                convo.history.append(Msg("user", "user", reply))
            else:
                convo.history.append(Msg("agent", convo.active, action["say"]))
                log(f"  [{convo.active}] says: {action['say']}")
                break
    return convo


def handoff_problem(convo: Convo, to: str, action: dict) -> str:
    if to not in ALLOWED.get(convo.active, set()):
        return f"{convo.active} may not transfer to {to}"
    if not action.get("reason"):
        return "no reason given"
    missing = REQUIRED_PAYLOAD - set(action.get("payload", {}))
    if missing:
        return f"payload missing {sorted(missing)}"
    path = [a for a, _ in convo.handoffs] + [convo.active, to]
    if len(path) >= 4 and path[-1] == path[-3] and path[-2] == path[-4]:
        return f"ping-pong between {path[-2]} and {path[-1]}"
    if len(convo.handoffs) >= 5:
        return "too many handoffs in one conversation"
    return ""


def main() -> None:
    turns = ["Hi, I'm customer C-1042. I was charged twice this month and the app crashes on login (version 4.2.0)."]
    answers = {"Could you give me your customer ID? It starts with C-.": "C-1042",
               "Which customer ID is this for?": "C-1042",
               "Which app version are you on? (Settings > About)": "4.2.0"}
    results = {}
    for policy in ["full", "summary", "structured"]:
        print(f"\nHandoff carries: {policy}")
        convo = run(turns, policy, user_answers=answers)
        results[policy] = convo
        print(f"  refunds: {REFUNDS}; questions back to the user: {convo.asked_user}")

    chatter = [f"Quick question {i}: is the office open on Saturday?" for i in range(1, 16)]
    long_tokens = {p: run(chatter + turns, p, user_answers=answers, log=lambda s: None).specialist_tokens
                   for p in results}
    print("\nSummary (tokens the specialists read: this conversation / with 15 earlier small-talk turns)")
    print(f"  {'policy':<11} {'handoffs':>8} {'re-asked':>9} {'specialist tokens':>18}")
    for policy, c in results.items():
        print(f"  {policy:<11} {len(c.handoffs):>8} {c.asked_user:>9} {c.specialist_tokens:>9} / {long_tokens[policy]:>6}")

    print("\nA ping-pong between two specialists")
    def billing_bounce(ctx, convo):
        return {"handoff": "tech", "reason": "sounds technical", "summary": "-",
                "payload": {"customer_id": "C-1042", "issues": ["?"], "done": []}}
    def tech_bounce(ctx, convo):
        return {"handoff": "billing", "reason": "sounds like billing", "summary": "-",
                "payload": {"customer_id": "C-1042", "issues": ["?"], "done": []}}
    bouncy = {**AGENTS, "billing": billing_bounce, "tech": tech_bounce}
    convo = run(["C-1042: my invoice page shows an error"], "structured", agents=bouncy)
    print(f"  handoffs before the guard stopped it: {convo.handoffs}")

    print("\nA handoff without the required payload")
    def sloppy_triage(ctx, convo):
        return {"handoff": "billing", "reason": "billing question", "summary": "billing", "payload": {"issues": ["billing"]}}
    run(["refund please"], "structured", agents={**AGENTS, "triage": sloppy_triage})


if __name__ == "__main__":
    main()
