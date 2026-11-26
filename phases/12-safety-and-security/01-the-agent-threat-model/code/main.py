"""The agent threat model: describe an agent's tools by what they touch, then let code find the
attack paths. An agent is exposed when one session can (1) read private data, (2) take in content
an attacker wrote, and (3) send something out. That's the "lethal trifecta". Add irreversible side
effects and an injection can act without exfiltrating anything.

    python3 main.py

Standard library only. No model needed: this is analysis of a design, done before you run anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

# ---------------------------------------------------------------- describing an agent


@dataclass(frozen=True)
class Tool:
    name: str
    private: bool = False        # returns data the user wouldn't want published (mail, files, DB rows)
    untrusted: bool = False      # returns content someone other than the user can write (web, inbound mail, issues)
    egress: bool = False         # can carry data out of the system (send, post, fetch a URL you choose)
    effect: str = "none"         # "none" | "reversible" | "irreversible"


@dataclass
class Agent:
    name: str
    tools: list[Tool]
    renders_markdown: bool = False   # the UI renders model output; an image URL is fetched with no click
    notes: str = ""

    def all_tools(self) -> list[Tool]:
        """The chat UI is a tool too: if it renders markdown, model output is an egress channel."""
        extra = [Tool("<rendered output>", egress=True)] if self.renders_markdown else []
        return self.tools + extra

# ---------------------------------------------------------------- finding attack paths


@dataclass
class Path:
    kind: str            # "exfiltration" or "injected action"
    steps: tuple[str, ...]
    severity: int        # 1 low .. 3 high

    def __str__(self) -> str:
        return f"[{self.kind}] " + " -> ".join(self.steps)


def legs(agent: Agent) -> dict[str, list[Tool]]:
    ts = agent.all_tools()
    return {"untrusted": [t for t in ts if t.untrusted],
            "private": [t for t in ts if t.private],
            "egress": [t for t in ts if t.egress],
            "irreversible": [t for t in ts if t.effect == "irreversible"]}


def attack_paths(agent: Agent) -> list[Path]:
    """Every way attacker-written content can lead to data leaving or a harmful action."""
    lg = legs(agent)
    paths = []
    for src, priv, out in product(lg["untrusted"], lg["private"], lg["egress"]):
        paths.append(Path("exfiltration", (f"{src.name} (injection)", f"{priv.name} (reads secret)",
                                           f"{out.name} (sends it out)"), 3))
    for src, act in product(lg["untrusted"], lg["irreversible"]):
        paths.append(Path("injected action", (f"{src.name} (injection)", f"{act.name} (irreversible)"), 2))
    return paths


def has_trifecta(agent: Agent) -> bool:
    lg = legs(agent)
    return bool(lg["untrusted"] and lg["private"] and lg["egress"])


def cheapest_cut(agent: Agent) -> tuple[str, list[str]]:
    """Breaking any one leg removes every exfiltration path. Pick the leg with the fewest tools
    to remove or gate. On a tie prefer egress, then untrusted: private data is usually the reason
    the agent exists, so it's the leg you least want to cut."""
    lg = legs(agent)
    order = ("egress", "untrusted", "private")
    options = {k: [t.name for t in lg[k]] for k in order}
    leg = min(order, key=lambda k: (len(options[k]), order.index(k)))
    return leg, options[leg]


def report(agent: Agent) -> dict:
    lg = legs(agent)
    paths = attack_paths(agent)
    leg, cut = cheapest_cut(agent) if has_trifecta(agent) else ("", [])
    return {"agent": agent.name, "trifecta": has_trifecta(agent),
            "legs": {k: [t.name for t in v] for k, v in lg.items()},
            "paths": paths, "cut_leg": leg, "cut_tools": cut}

# ---------------------------------------------------------------- three agents

INBOX = Agent("inbox assistant", [
    Tool("read_email", private=True, untrusted=True),          # your mail, written by strangers
    Tool("search_drive", private=True),
    Tool("fetch_url", untrusted=True, egress=True),            # the URL itself can carry data out
    Tool("send_email", egress=True, effect="irreversible"),
], renders_markdown=True, notes="every leg, and two tools sit on two legs")

DOCS_BOT = Agent("public docs bot", [
    Tool("search_public_docs"),                                # written by your own team, public anyway
    Tool("open_ticket", effect="reversible"),
], renders_markdown=False, notes="no private data, no attacker content")

CODER = Agent("coding agent", [
    Tool("read_file", private=True),                           # .env, keys, source
    Tool("read_issue", untrusted=True),                        # anyone can open a GitHub issue
    Tool("run_shell", private=True, egress=True, effect="irreversible"),
    Tool("git_push", egress=True, effect="irreversible"),
], renders_markdown=True, notes="the shell is every leg except untrusted input")

AGENTS = [INBOX, DOCS_BOT, CODER]


if __name__ == "__main__":
    for agent in AGENTS:
        r = report(agent)
        print(f"== {r['agent']}  ({agent.notes})")
        for k, v in r["legs"].items():
            print(f"   {k:<13}{', '.join(v) or '-'}")
        kinds = {}
        for p in r["paths"]:
            kinds[p.kind] = kinds.get(p.kind, 0) + 1
        print(f"   trifecta:    {'YES' if r['trifecta'] else 'no'}   paths: "
              + (", ".join(f"{n} {k}" for k, n in kinds.items()) or "none"))
        for p in r["paths"][:3]:
            print(f"     {p}")
        if len(r["paths"]) > 3:
            print(f"     ... {len(r['paths']) - 3} more")
        if r["trifecta"]:
            print(f"   cheapest cut: the {r['cut_leg']} leg -> remove or gate {', '.join(r['cut_tools'])}")
        print()
