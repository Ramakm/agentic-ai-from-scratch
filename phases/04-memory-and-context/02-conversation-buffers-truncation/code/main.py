"""Conversation buffers and truncation: keep the history inside the budget without breaking it.

Four buffer strategies over the same 36-message conversation: keep everything, keep the last N
messages (naive and safe), and a token window that pins the system prompt and the first user turn
and never splits a tool call from its results.

    python3 main.py             # offline: compare the strategies with a scripted model
    python3 main.py --live      # live: send each buffer to a real model and ask what it remembers
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Callable

# ---------------------------------------------------------------- counting


def tokens(message: dict) -> int:
    """~4 characters per token, plus a few for the role and message framing."""
    return len(json.dumps(message)) // 4 + 4


def total(messages: list[dict]) -> int:
    return sum(tokens(m) for m in messages)

# ---------------------------------------------------------------- structure


def groups(messages: list[dict]) -> list[list[dict]]:
    """Split history into atomic units. An assistant message with tool_calls and the tool results
    that answer it form one unit: keep all of it or none of it."""
    out: list[list[dict]] = []
    for m in messages:
        if m["role"] == "tool" and out and out[-1][0].get("tool_calls"):
            out[-1].append(m)
        else:
            out.append([m])
    return out


def validate(messages: list[dict]) -> list[str]:
    """Problems a provider would reject: tool results with no matching call, calls with no result."""
    problems, pending = [], set()
    for i, m in enumerate(messages):
        if m["role"] == "tool":
            if m.get("tool_call_id") not in pending:
                problems.append(f"message {i}: tool result {m.get('tool_call_id')} has no matching tool call")
            pending.discard(m.get("tool_call_id"))
        else:
            if pending and m["role"] != "tool":
                problems.append(f"message {i}: tool calls {sorted(pending)} have no results")
                pending.clear()
            for call in m.get("tool_calls") or []:
                pending.add(call["id"])
    if pending:
        problems.append(f"end: tool calls {sorted(pending)} have no results")
    return problems

# ---------------------------------------------------------------- strategies


def keep_all(messages: list[dict], **_: int) -> list[dict]:
    return list(messages)


def last_n_naive(messages: list[dict], n: int = 13, **_: int) -> list[dict]:
    """System prompt plus the last n messages. Simple, and it can cut a tool call in half."""
    system = [m for m in messages[:1] if m["role"] == "system"]
    return system + messages[len(system):][-n:]


def last_n_safe(messages: list[dict], n: int = 13, **_: int) -> list[dict]:
    """Like last_n_naive, but drop leading messages until the tail starts on a whole unit."""
    system = [m for m in messages[:1] if m["role"] == "system"]
    tail = messages[len(system):][-n:]
    while tail and tail[0]["role"] == "tool":
        tail = tail[1:]
    return system + tail


MARKER_COST = 25


def token_window(messages: list[dict], budget: int = 600, pin_first_user: bool = True, **_: int) -> list[dict]:
    """Keep the system prompt and (optionally) the first user message, then add whole units from
    the newest backwards while they fit. Insert a marker where history was cut."""
    units = groups(messages)
    head: list[list[dict]] = []
    if units and units[0][0]["role"] == "system":
        head.append(units.pop(0))
    if pin_first_user and units and units[0][0]["role"] == "user":
        head.append(units.pop(0))
    used = sum(total(u) for u in head) + MARKER_COST     # reserve room for the "removed" marker
    tail: list[list[dict]] = []
    for unit in reversed(units):
        if used + total(unit) > budget:
            break
        tail.insert(0, unit)
        used += total(unit)
    cut = len(units) - len(tail)
    marker = [[{"role": "user", "content": f"[{cut} earlier messages were removed to save space]"}]] if cut else []
    return [m for u in head + marker + tail for m in u]


STRATEGIES: dict[str, Callable[..., list[dict]]] = {
    "keep all": keep_all,
    "last 13 (naive)": last_n_naive,
    "last 13 (safe)": last_n_safe,
    "token window 600": token_window,
}

# ---------------------------------------------------------------- a long conversation


def tool_call(i: int, city: str) -> list[dict]:
    cid = f"call_{i}"
    return [{"role": "assistant", "content": "", "tool_calls": [{"id": cid, "type": "function", "function": {
                "name": "weather", "arguments": json.dumps({"city": city})}}]},
            {"role": "tool", "tool_call_id": cid, "content": f"{city}: 21C, light wind, 10% rain"}]


def conversation() -> list[dict]:
    msgs = [{"role": "system", "content": "You are a friendly travel assistant. Be brief."},
            {"role": "user", "content": "Hi, I'm Arjun. I'm planning a trip to Lisbon in May, budget 1,500 euros."},
            {"role": "assistant", "content": "Great choice, Arjun. What would you like to plan first?"}]
    topics = ["hotels in Alfama", "the tram 28 route", "day trip to Sintra", "pasteis de nata",
              "fado venues", "the Belem tower", "beaches near Cascais", "museum passes",
              "airport transfer", "a dinner spot", "a rainy-day plan", "what to pack"]
    for i, topic in enumerate(topics):
        msgs.append({"role": "user", "content": f"Tell me about {topic}."})
        if i % 3 == 1:
            msgs.extend(tool_call(i, "Lisbon"))
        msgs.append({"role": "assistant", "content": f"Here are a few tips about {topic}: book early, "
                                                     f"go in the morning, and keep an eye on the budget."})
    msgs.append({"role": "user", "content": "Remind me: what's my name, and what's my budget?"})
    return msgs

# ---------------------------------------------------------------- models

LLM = Callable[[list[dict]], str]


def scripted(messages: list[dict]) -> str:
    """Answers from the window only, like a real model. No name in the window, no name in the answer."""
    window = " ".join(str(m.get("content") or "") for m in messages)
    name = "Arjun" if "I'm Arjun" in window else None
    budget = "1,500 euros" if "1,500 euros" in window else None
    if name and budget:
        return f"You're {name}, and your budget is {budget}."
    return "Sorry, I don't have your name or budget in this conversation. Could you remind me?"


def openai_compatible(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list[dict]) -> str:
        body = {"model": model, "messages": messages, "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)["choices"][0]["message"]["content"] or ""
        except urllib.error.HTTPError as exc:     # an invalid history is an observation, not a crash
            return f"HTTP {exc.code}: {exc.read().decode()[:120]}"
    return call


def compare(llm: LLM) -> list[dict]:
    history = conversation()
    rows = []
    for label, strategy in STRATEGIES.items():
        kept = strategy(history)
        rows.append({"strategy": label, "messages": len(kept), "tokens": total(kept),
                     "problems": validate(kept), "answer": llm(kept)})
    return rows


if __name__ == "__main__":
    llm: LLM = scripted
    if "--live" in sys.argv:
        llm = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
    print(f"conversation: {len(conversation())} messages, ~{total(conversation())} tokens\n")
    for r in compare(llm):
        status = "valid" if not r["problems"] else f"INVALID: {r['problems'][0]}"
        print(f"{r['strategy']:18} {r['messages']:3} msgs  ~{r['tokens']:5} tokens  {status}")
        print(f"{'':18} answer: {r['answer'][:100]}")
