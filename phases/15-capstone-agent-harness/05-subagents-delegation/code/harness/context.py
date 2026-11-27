"""Context and memory: what the model sees on each call, and what survives between runs.

ContextManager is a hook. Before every model call it keeps the history under a token budget in two
passes: first it clips old tool results (cheap, usually enough), then it compacts the oldest turns
into one summary message. The system prompt, the task and the most recent turns are never touched.

Memory is a small JSON file of notes with provenance, exposed to the model as remember/recall tools.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable

from .hooks import Hook, RunState
from .llm import estimate_tokens
from .tools import Tool, schema_from_function

INSTRUCTION_FILES = ("HARNESS.md", "AGENTS.md", "CLAUDE.md")
SUMMARY_HEAD = "[harness: summary of earlier work in this task]"


class ContextManager(Hook):
    def __init__(self, budget_tokens: int = 8000, keep_recent: int = 6, clip_chars: int = 300,
                 summarize: Callable[[list[dict]], str] | None = None) -> None:
        self.budget, self.keep_recent, self.clip_chars = budget_tokens, max(1, keep_recent), clip_chars
        self.summarize = summarize or extractive_summary
        self.events: list[str] = []                 # what it did, for the demo and the tracer

    def before_model(self, state: RunState, messages: list[dict]) -> list[dict]:
        before = estimate_tokens(messages)
        if before <= self.budget:
            return messages
        head = 2 if messages and messages[0]["role"] == "system" else 1      # system + task stay
        cut = self._cut(messages, head)
        # pass 1: clip tool results older than the recent window
        out = [dict(m) for m in messages]
        clipped = 0
        for m in out[head:cut]:
            if m["role"] == "tool" and len(m.get("content") or "") > self.clip_chars:
                full = len(m["content"])
                m["content"] = m["content"][: self.clip_chars] + f"\n[clipped by harness: {full:,} chars; call the tool again if you need it]"
                clipped += 1
        if clipped:
            self.events.append(f"step {state.step}: clipped {clipped} old tool result(s), {before} -> {estimate_tokens(out)} tokens")
        if estimate_tokens(out) <= self.budget or cut <= head:
            return out
        # pass 2: compact everything between the task and the recent window into one summary
        middle = out[head:cut]
        summary = {"role": "user", "content": SUMMARY_HEAD + "\n" + self.summarize(middle)}
        compacted = out[:head] + [summary] + out[cut:]
        self.events.append(f"step {state.step}: compacted {len(middle)} message(s) into a summary, "
                           f"{estimate_tokens(out)} -> {estimate_tokens(compacted)} tokens")
        return compacted

    def _cut(self, messages: list[dict], head: int) -> int:
        """Start of the recent window. It must begin at an assistant message, so a tool result is never
        separated from the call that asked for it (APIs reject a tool message with no matching call)."""
        cut = max(head, len(messages) - self.keep_recent)
        while cut > head and messages[cut]["role"] != "assistant":
            cut -= 1
        return cut


def extractive_summary(messages: list[dict]) -> str:
    """A summary without a model call: what was done and the first line of what came back.

    Swap in an LLM summarizer for better recall; this one is free, deterministic, and never invents.
    """
    lines, pending = [], {}
    for m in messages:
        if m["role"] == "assistant":
            if m.get("content"):
                lines.append(f"- noted: {m['content'].strip().splitlines()[0][:160]}")
            for c in m.get("tool_calls") or []:
                pending[c.get("id", "")] = f"{c['function']['name']}({c['function'].get('arguments', '')[:80]})"
        elif m["role"] == "tool":
            first = (m.get("content") or "").strip().splitlines()[:1]
            lines.append(f"- {pending.get(m.get('tool_call_id', ''), 'tool')} -> {first[0][:120] if first else '(empty)'}")
        elif m["role"] == "user":
            text = m.get("content") or ""
            if text.startswith(SUMMARY_HEAD):           # an earlier summary: keep its lines, don't re-summarise
                lines += text.splitlines()[1:]
            else:
                lines.append(f"- user: {text[:160]}")
    return "\n".join(lines)


def llm_summarizer(llm) -> Callable[[list[dict]], str]:
    """Summarize with a model. Better recall than extractive_summary; costs a call, and can invent."""
    def summarize(messages: list[dict]) -> str:
        transcript = extractive_summary(messages)
        reply = llm([{"role": "system", "content": "Summarize this agent work log for the agent itself. Keep file "
                      "names, numbers, decisions and open questions. Under 150 words. No preamble."},
                     {"role": "user", "content": transcript}], [])
        return (reply.get("content") or transcript).strip()
    return summarize


def project_instructions(root: str | Path, max_chars: int = 4000) -> str:
    """The first instruction file found in the workspace root, for the system prompt."""
    for name in INSTRUCTION_FILES:
        p = Path(root) / name
        if p.is_file():
            text = p.read_text(errors="replace")
            cut = f"\n[{name} truncated at {max_chars} chars]" if len(text) > max_chars else ""
            return f"Project instructions from {name}:\n{text[:max_chars]}{cut}"
    return ""


# ---------------------------------------------------------------- long-term memory

SUSPICIOUS = re.compile(r"ignore (all |any |previous |prior )*(instructions|rules)|you must now|system prompt|"
                        r"exfiltrate|send .* to http", re.I)


class Memory:
    """Notes that survive between runs, in a JSON file. Each note keeps where it came from."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.notes: list[dict] = []
        if self.path and self.path.exists():
            self.notes = json.loads(self.path.read_text() or "[]")

    def add(self, text: str, tags: list[str] | None = None, source: str = "agent") -> dict:
        text = " ".join(text.split())
        if not text:
            raise ValueError("empty note")
        if SUSPICIOUS.search(text):
            raise ValueError("refused: this note reads like an instruction to the agent, not a fact. "
                             "Memory stores facts and preferences only.")
        for n in self.notes:                       # same fact again: refresh, don't duplicate
            if n["text"].lower() == text.lower():
                n["updated"] = time.strftime("%Y-%m-%d")
                self._save()
                return n
        note = {"id": len(self.notes) + 1, "text": text, "tags": tags or [], "source": source,
                "updated": time.strftime("%Y-%m-%d")}
        self.notes.append(note)
        self._save()
        return note

    def search(self, query: str, k: int = 5) -> list[dict]:
        words = set(re.findall(r"\w{3,}", query.lower()))
        scored = []
        for n in self.notes:
            have = set(re.findall(r"\w{3,}", (n["text"] + " " + " ".join(n["tags"])).lower()))
            if words & have:
                scored.append((len(words & have), n["id"], n))
        return [n for _, _, n in sorted(scored, key=lambda x: (-x[0], -x[1]))[:k]]

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.notes, indent=2))

    # ---- as tools
    def remember(self, text: str, tags: str = "") -> str:
        """Save a durable fact or user preference for future sessions. Not for task progress.

        text: one self-contained fact, e.g. 'Tests run with: make test'
        tags: comma-separated keywords
        """
        n = self.add(text, [t.strip() for t in tags.split(",") if t.strip()])
        return f"remembered #{n['id']}: {n['text']}"

    def recall(self, query: str) -> str:
        """Search saved notes from earlier sessions.

        query: words to look for
        """
        hits = self.search(query)
        if not hits:
            return f"no notes match {query!r}"
        return "\n".join(f"#{n['id']} ({n['source']}, {n['updated']}): {n['text']}" for n in hits)

    def tools(self) -> list[Tool]:
        return [Tool("remember", "Save a durable fact or user preference for future sessions. Not for task progress.",
                     schema_from_function(self.remember), lambda a: self.remember(**a), read_only=False),
                Tool("recall", "Search saved notes from earlier sessions.",
                     schema_from_function(self.recall), lambda a: self.recall(**a), read_only=True)]
