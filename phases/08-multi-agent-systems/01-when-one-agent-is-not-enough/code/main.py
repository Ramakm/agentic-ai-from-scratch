"""When one agent is not enough: measure the two pressures that push you to split an agent
(too many tools to choose from, too much context in one window), and the price of splitting.

    python3 main.py           # offline: a word-overlap tool picker stands in for the model
    python3 main.py --live    # the model picks tools (AGENT_BASE_URL, AGENT_MODEL, AGENT_API_KEY)

The stand-in picker confuses similar tools for the same reason models do (overlapping names and
descriptions), but its accuracy numbers are about this toy, not about any real model.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

# --------------------------------------------------------------------------------------------
# 24 tools in 4 domains, with the overlaps real tool sets have
# --------------------------------------------------------------------------------------------

DOMAINS = {
    "docs": "documents, files, wiki pages, policies and runbooks",
    "tickets": "support tickets, incidents, bugs and their status",
    "crm": "customers, accounts, deals, contacts and sales pipeline",
    "calendar": "meetings, events, availability and scheduling",
}
# A router only works as well as its domain descriptions. These say what each specialist covers,
# in the words requests actually use (ids, verbs, objects).
DOMAINS_SPECIFIC = {
    "docs": "documents and DOC ids, wiki pages, policies, runbooks, reports: open, write, edit, fix typos, share",
    "tickets": "support tickets and INC ids, incidents, bugs, priority, status, comments: report a bug",
    "crm": "customers, accounts and ACC ids, contacts, deals, sales pipeline, calls with customers",
    "calendar": "meetings, events and EVT ids, 1:1s, scheduling, moving meetings, availability, free time",
}
TOOLS = {
    "docs": {"search": "Search documents and wiki pages by keywords.",
             "get": "Get a document by its id.",
             "create": "Create a new document or wiki page.",
             "update": "Update the text of a document.",
             "list_recent": "List recently edited documents.",
             "share": "Share a document with a person."},
    "tickets": {"search": "Search support tickets by keywords.",
                "get": "Get a ticket by its id, with status and history.",
                "create": "Create a support ticket for a bug or incident.",
                "update": "Update a ticket's status, priority or assignee.",
                "list_open": "List open tickets, newest first.",
                "comment": "Add a comment to a ticket."},
    "crm": {"search": "Search customers and accounts by name.",
            "get": "Get an account by its id, with contacts and deals.",
            "create": "Create a new contact or account.",
            "update": "Update a deal's stage or amount.",
            "list_deals": "List open deals in the pipeline.",
            "log_call": "Log a call or meeting with a customer."},
    "calendar": {"search": "Search calendar events by title.",
                 "get": "Get an event by its id.",
                 "create": "Create a meeting or event and invite people.",
                 "update": "Move or change a meeting.",
                 "list_today": "List today's meetings.",
                 "free_slots": "Find free time slots for a group of people."},
}

# (request, gold domain, gold tool)
REQUESTS = [
    ("Find the runbook about database failover", "docs", "search"),
    ("Open document DOC-88", "docs", "get"),
    ("Write a new wiki page for the onboarding checklist", "docs", "create"),
    ("Fix a typo in the travel policy document", "docs", "update"),
    ("What documents were edited recently?", "docs", "list_recent"),
    ("Share the Q3 report document with Priya", "docs", "share"),
    ("Look for tickets about login failures", "tickets", "search"),
    ("Show ticket INC-311 and its history", "tickets", "get"),
    ("Report a bug: export button crashes", "tickets", "create"),
    ("Set INC-311 priority to high", "tickets", "update"),
    ("Which incidents are still open?", "tickets", "list_open"),
    ("Add a comment on INC-311 that the fix is deployed", "tickets", "comment"),
    ("Find the customer account for Acme", "crm", "search"),
    ("Pull up account ACC-7 with its contacts", "crm", "get"),
    ("Add Dana Lee from Globex as a new contact", "crm", "create"),
    ("Move the Acme deal to negotiation stage", "crm", "update"),
    ("Show open deals in the sales pipeline", "crm", "list_deals"),
    ("Log my call with Acme's CFO", "crm", "log_call"),
    ("Find the event called design review", "calendar", "search"),
    ("Show event EVT-3", "calendar", "get"),
    ("Set up a meeting with Ana and Ben on Friday", "calendar", "create"),
    ("Move my 1:1 to Thursday", "calendar", "update"),
    ("What meetings do I have today?", "calendar", "list_today"),
    ("When are Ana, Ben and Cy all free next week?", "calendar", "free_slots"),
]

WORD = re.compile(r"[a-z0-9]+")
STOP = {"a", "an", "the", "and", "or", "by", "its", "it", "my", "to", "of", "for", "with", "on", "in",
        "is", "are", "at", "all", "what", "which", "do", "i", "have", "about", "that", "show", "find"}


def words(text: str) -> set[str]:
    out = set()
    for w in WORD.findall(text.lower()):
        if w not in STOP:
            out.add(w[:-1] if w.endswith("s") and len(w) > 3 else w)  # crude singular
    return out


def stand_in_pick(request: str, options: dict[str, str]) -> str:
    """Pick the option whose name + description shares the most words with the request.
    Ties go to the first option in list order, which is where similar tools get confused."""
    req = words(request)
    return max(options, key=lambda k: len(req & words(k.replace("_", " ") + " " + options[k])))


def live_pick(request: str, options: dict[str, str]) -> str:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    listing = "\n".join(f"- {k}: {v}" for k, v in options.items())
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0, "messages": [
        {"role": "system", "content": "Pick the single best option for the request. Reply with its name only."},
        {"role": "user", "content": f"Options:\n{listing}\n\nRequest: {request}"}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        text = json.loads(resp.read())["choices"][0]["message"]["content"].strip()
    return next((k for k in options if k in text), text)


def all_tools() -> dict[str, str]:
    return {f"{d}.{t}": desc for d, tools in TOOLS.items() for t, desc in tools.items()}


def tokens(options: dict[str, str]) -> int:
    return len(json.dumps(options)) // 4


def single_agent(request: str, pick) -> tuple[str, int, int]:
    options = all_tools()
    return pick(request, options), 1, tokens(options)


def routed(request: str, pick, domain_text: dict = DOMAINS) -> tuple[str, int, int]:
    domains = {d: f"Handles {desc}." for d, desc in domain_text.items()}
    domain = pick(request, domains)
    tools = {f"{domain}.{t}": desc for t, desc in TOOLS.get(domain, {}).items()}
    if not tools:
        return f"{domain}.?", 1, tokens(domains)
    return pick(request, tools), 2, tokens(domains) + tokens(tools)


def evaluate(strategy, pick) -> dict:
    right, calls, toks, misses = 0, 0, 0, []
    for request, domain, tool in REQUESTS:
        got, c, t = strategy(request, pick)
        calls, toks = calls + c, toks + t
        if got == f"{domain}.{tool}":
            right += 1
        else:
            misses.append(f"{request!r}: picked {got}, wanted {domain}.{tool}")
    return {"right": right, "calls": calls, "tokens": toks, "misses": misses}


# --------------------------------------------------------------------------------------------
# Context pressure: three research threads in one window vs three windows
# --------------------------------------------------------------------------------------------

THREADS = {"pricing": [3200, 2800, 4100], "security": [5200, 3900], "integrations": [2600, 3100, 2900, 3300]}
SUMMARY_TOKENS = 400  # each worker hands back a summary this size
BRIEF_TOKENS = 800    # system prompt + task, re-read on every model call
WINDOW = 16000


def tokens_read(results: list[int]) -> int:
    """One model call after each tool result; each call re-reads the brief and everything so far."""
    total, context = 0, 0
    for r in results:
        context += r
        total += BRIEF_TOKENS + context
    return total


def context_profile() -> dict:
    single = 0
    peak_single = 0
    for results in THREADS.values():
        for r in results:
            single += r
            peak_single = max(peak_single, single)
    workers = {name: sum(results) for name, results in THREADS.items()}
    lead = SUMMARY_TOKENS * len(THREADS)
    every = [r for results in THREADS.values() for r in results]
    read_single = tokens_read(every)
    read_split = sum(tokens_read(results) for results in THREADS.values()) + BRIEF_TOKENS + lead
    return {"single_peak": peak_single, "worker_peaks": workers, "lead": lead,
            "read_single": read_single, "read_split": read_split}


# --------------------------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------------------------

TASKS = [
    {"task": "Answer a question about the expense policy", "tools": 2, "context_tokens": 3000,
     "independent_parts": 1, "separate_permissions": False},
    {"task": "Triage a support inbox using tickets, docs and CRM (24 tools)", "tools": 24, "context_tokens": 9000,
     "independent_parts": 1, "separate_permissions": False},
    {"task": "Research 3 vendors on pricing, security and integrations", "tools": 4, "context_tokens": 34000,
     "independent_parts": 3, "separate_permissions": False},
    {"task": "Read untrusted emails and also send payments", "tools": 6, "context_tokens": 5000,
     "independent_parts": 1, "separate_permissions": True},
    {"task": "Refactor one function and run its tests", "tools": 5, "context_tokens": 12000,
     "independent_parts": 1, "separate_permissions": False},
]


def assess(t: dict, tool_limit: int = 12, window: int = WINDOW) -> tuple[str, list[str]]:
    reasons = []
    if t["separate_permissions"]:
        reasons.append("parts need different trust levels: isolate them (reader without side-effect tools)")
    if t["independent_parts"] > 1 and t["context_tokens"] > window:
        reasons.append(f"{t['independent_parts']} independent parts and {t['context_tokens']} tokens > "
                       f"{window} window: orchestrator-worker")
    elif t["independent_parts"] > 1:
        reasons.append("independent parts, but they fit one window: parallel tool calls may be enough")
    if t["tools"] > tool_limit:
        reasons.append(f"{t['tools']} tools > {tool_limit}: route to specialists (or select tools per task)")
    if t["context_tokens"] > window and t["independent_parts"] == 1:
        reasons.append("context too big but not separable: compress or summarise (Phase 4), don't split")
    split = any("isolate" in r or "orchestrator" in r or "route" in r for r in reasons)
    return ("multi-agent" if split else "one agent"), reasons or ["fits one agent: small tool set, one window"]


def main() -> None:
    live = "--live" in sys.argv
    pick = live_pick if live else stand_in_pick
    print(f"Tool choice with {len(all_tools())} tools ({'live model' if live else 'word-overlap stand-in'})")
    one = evaluate(single_agent, pick)
    vague = evaluate(routed, pick)
    good = evaluate(lambda r, p: routed(r, p, DOMAINS_SPECIFIC), pick)
    n = len(REQUESTS)
    for label, res in [("one agent, all tools", one), ("router (vague domains) + specialist", vague),
                       ("router (specific domains) + specialist", good)]:
        print(f"  {label:<40} {res['right']:>2}/{n} right, {res['calls']} calls, "
              f"~{res['tokens'] // n} tokens of options per request")
    for label, res in [("one agent", one), ("vague router", vague), ("specific router", good)]:
        print(f"  {label} misses:")
        for m in res["misses"] or ["none"]:
            print(f"    {m}")

    print(f"\nContext: three research threads ({WINDOW}-token window)")
    p = context_profile()
    print(f"  one agent holds every result:   peak {p['single_peak']} tokens "
          f"({'over' if p['single_peak'] > WINDOW else 'within'} the window)")
    for name, peak in p["worker_peaks"].items():
        print(f"  worker '{name}':{' ' * (14 - len(name))}peak {peak} tokens")
    print(f"  lead agent reads 3 summaries:   {p['lead']} tokens")
    print(f"  tokens read over all model calls: one agent {p['read_single']}, split {p['read_split']}")
    print("  (each call re-reads its own context; workers never re-read each other's results)")

    print("\nDecisions")
    for t in TASKS:
        verdict, reasons = assess(t)
        print(f"  {t['task']}\n    -> {verdict}: {'; '.join(reasons)}")


if __name__ == "__main__":
    main()
