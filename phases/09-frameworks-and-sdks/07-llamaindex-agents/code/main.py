"""LlamaIndex's agent core, rebuilt: indexes wrapped as query engines, query engines wrapped
as tools, and a text ReAct agent that picks among them.

    python3 main.py                  # offline, scripted model
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py

The same agent on the real library is in with_llamaindex.py (pip install llama-index-core).
Standard library only.
"""
from __future__ import annotations

import ast
import inspect
import json
import math
import os
import re
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

LLM = Callable[[str], str]                  # completion-style: prompt -> text, like LlamaIndex's ReAct path

# ---------------------------------------------------------------- index + query engine

@dataclass
class Document:
    text: str
    source: str


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class KeywordIndex:
    """BM25 over sentences. Phase 5 built the real thing; this is enough to route questions."""

    def __init__(self, docs: list[Document], k1: float = 1.5, b: float = 0.75):
        self.chunks = [(s.strip(), d.source) for d in docs for s in re.split(r"(?<=[.!?])\s+", d.text) if s.strip()]
        self.tf = [Counter(tokens(c)) for c, _ in self.chunks]
        self.avg = sum(sum(t.values()) for t in self.tf) / max(len(self.tf), 1)
        df = Counter(w for t in self.tf for w in t)
        n = len(self.chunks)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.k1, self.b = k1, b

    def retrieve(self, query: str, top_k: int = 2) -> list[tuple[str, str, float]]:
        scored = []
        for (chunk, src), tf in zip(self.chunks, self.tf):
            length = sum(tf.values())
            s = sum(self.idf.get(w, 0) * tf[w] * (self.k1 + 1) /
                    (tf[w] + self.k1 * (1 - self.b + self.b * length / self.avg)) for w in tokens(query) if w in tf)
            if s > 0:
                scored.append((chunk, src, round(s, 2)))
        return sorted(scored, key=lambda x: -x[2])[:top_k]


SYNTHESIS = ("Context information is below.\n---------------------\n{context}\n---------------------\n"
             "Given the context information and not prior knowledge, answer the query.\nQuery: {query}\nAnswer: ")


@dataclass
class QueryEngine:
    """Retrieve, then ask the model to answer from the retrieved text only. One model call per query."""
    index: KeywordIndex
    llm: LLM
    top_k: int = 2
    last_sources: list[str] = field(default_factory=list)

    def query(self, q: str) -> str:
        hits = self.index.retrieve(q, self.top_k)
        self.last_sources = [src for _, src, _ in hits]
        if not hits:
            return "Empty Response"
        context = "\n\n".join(f"source: {src}\n\n{chunk}" for chunk, src, _ in hits)
        return self.llm(SYNTHESIS.format(context=context, query=q)).strip()

# ---------------------------------------------------------------- tools

@dataclass
class Tool:
    name: str
    description: str
    params: dict
    fn: Callable[..., Any]

    def __call__(self, **kwargs: Any) -> str:
        return str(self.fn(**kwargs))


def function_tool(fn: Callable[..., Any]) -> Tool:
    sig = inspect.signature(fn)
    kinds = {int: "integer", float: "number", str: "string", bool: "boolean"}
    props = {n: {"type": kinds.get(p.annotation, "string")} for n, p in sig.parameters.items()}
    return Tool(fn.__name__, f"{fn.__name__}{sig}\n{(fn.__doc__ or '').strip()}",
                {"properties": props, "required": list(props), "type": "object"}, fn)


def query_engine_tool(engine: QueryEngine, name: str, description: str) -> Tool:
    return Tool(name, description, {"properties": {"input": {"type": "string"}}, "required": ["input"], "type": "object"},
                lambda input: engine.query(input))

# ---------------------------------------------------------------- the ReAct agent

REACT_HEADER = """You are designed to help with a variety of tasks, from answering questions to providing summaries to other types of analyses.

## Tools

You have access to the following tools:
{tools}

## Output Format

Please answer in the same language as the question and use the following format:

Thought: I need to use a tool to help me answer the question.
Action: tool name (one of {names}) if using a tool.
Action Input: the input to the tool, in a JSON format representing the kwargs (e.g. {{"input": "hello world"}})

When you can answer, use:

Thought: I can answer without using any more tools.
Answer: [your answer here]

## Current Conversation

"""


@dataclass
class Step:
    thought: str = ""
    action: str = ""
    action_input: dict = field(default_factory=dict)
    answer: str | None = None


class ParseError(ValueError):
    pass


def parse_react(text: str) -> Step:
    thought = (re.search(r"Thought:\s*(.*?)(?=\n(?:Action|Answer):|\Z)", text, re.S) or [None, ""])[1].strip()
    answer = re.search(r"Answer:\s*(.*)", text, re.S)
    if answer:
        return Step(thought, answer=answer.group(1).strip())
    action = re.search(r"Action:\s*([\w\-]+)", text)
    raw = re.search(r"Action Input:\s*(\{.*\})", text, re.S)
    if not action:
        raise ParseError("Could not parse output. Use 'Action:' with a tool name, or 'Answer:'.")
    if not raw:
        raise ParseError("Action Input must be a JSON object.")
    try:
        args = json.loads(raw.group(1))
    except json.JSONDecodeError:
        try:                                              # models often emit Python-style dicts; literal_eval
            args = ast.literal_eval(raw.group(1))         # parses literals only, it never runs code
        except (ValueError, SyntaxError) as exc:
            raise ParseError(f"Action Input is not valid JSON: {exc}") from exc
    if not isinstance(args, dict):
        raise ParseError("Action Input must be a JSON object.")
    return Step(thought, action.group(1), args)


@dataclass
class ReActAgent:
    tools: list[Tool]
    llm: LLM
    max_iterations: int = 10
    trace: list[str] = field(default_factory=list)

    def prompt(self, question: str, history: list[str]) -> str:
        tools = "\n".join(f"> Tool Name: {t.name}\nTool Description: {t.description}\nTool Args: {json.dumps(t.params)}\n"
                          for t in self.tools)
        header = REACT_HEADER.format(tools=tools, names=", ".join(t.name for t in self.tools))
        return header + f"user: {question}\n" + "".join(history) + "assistant: "

    def run(self, question: str) -> str:
        history: list[str] = []
        by_name = {t.name: t for t in self.tools}
        for _ in range(self.max_iterations):
            reply = self.llm(self.prompt(question, history))
            history.append(f"assistant: {reply.strip()}\n")
            try:
                step = parse_react(reply)
            except ParseError as exc:
                self.trace.append(f"parse error -> {exc}")
                history.append(f"user: Observation: Error: {exc}\n")
                continue
            if step.answer is not None:
                self.trace.append(f"answer: {step.answer}")
                return step.answer
            tool = by_name.get(step.action)
            try:
                obs = tool(**step.action_input) if tool else f"Error: no tool named {step.action!r}"
            except Exception as exc:  # noqa: BLE001
                obs = f"Error: {type(exc).__name__}: {exc}"
            self.trace.append(f"{step.action}({json.dumps(step.action_input)}) -> {obs}")
            history.append(f"user: Observation: {obs}\n")
        return f"Reached max iterations ({self.max_iterations}) without an answer."

# ---------------------------------------------------------------- demo

HR_DOCS = [Document("Employees get 24 vacation days per year. Unused days expire in March. "
                    "Sick leave is separate and unlimited with a doctor's note.", "hr/leave.md")]
IT_DOCS = [Document("Laptops are replaced every 3 years. Lost laptops must be reported to security within 24 hours.",
                    "it/devices.md")]


def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a - b


DEMO_REPLIES = [
    'Thought: I need the vacation policy.\nAction: hr_policies\nAction Input: {"input": "annual vacation days"}',
    "Employees get 24 vacation days per year.",                             # the query engine's synthesis call
    'Thought: Now subtract.\nAction: subtract\nAction Input: {"a": 24, "b": 9}',
    "Thought: I can answer.\nAnswer: You have 15 vacation days left (24 per year, 9 used). Source: hr/leave.md",
]


class Recorder:
    def __init__(self, llm: LLM):
        self.llm, self.prompts = llm, []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.llm(prompt)


def scripted_llm(replies: list[str]) -> LLM:
    queue = list(replies)
    return lambda prompt: queue.pop(0)


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(prompt: str) -> str:
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "stop": ["Observation:"]}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["choices"][0]["message"]["content"] or ""
    return call


def build_agent(llm: LLM) -> tuple[ReActAgent, QueryEngine]:
    hr = QueryEngine(KeywordIndex(HR_DOCS), llm)
    it = QueryEngine(KeywordIndex(IT_DOCS), llm)
    tools = [query_engine_tool(hr, "hr_policies", "HR policies: vacation, sick leave, benefits."),
             query_engine_tool(it, "it_policies", "IT policies: laptops, accounts, security."),
             function_tool(subtract)]
    return ReActAgent(tools, llm), hr


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    llm = Recorder(openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
                   if base else scripted_llm(DEMO_REPLIES))
    agent, hr = build_agent(llm)
    answer = agent.run("I've used 9 vacation days. How many are left?")
    for line in agent.trace:
        print(line)
    print(f"\nmodel calls: {len(llm.prompts)} (3 agent steps + 1 inside the hr_policies query engine)")
    print(f"sources retrieved by hr_policies: {hr.last_sources}")
    print(f"\n--- the query engine's prompt ---\n{llm.prompts[1]}")
