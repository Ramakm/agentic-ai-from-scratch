"""Choosing (or skipping) a framework: score options against your requirements, and audit
how locked-in an existing codebase already is.

    python3 main.py                                  # three example projects + audit of sample_app/
    python3 main.py --needs durable_state human_approval --avoid-deps
    python3 main.py --audit path/to/your/repo

Every capability score below is an OPINION, drawn from Lessons 2-8 of this phase. It is
written down so you can argue with it: change the numbers for your team and re-run.
Standard library only.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

NEEDS = {
    "durable_state": "Resume after crashes; pause for hours",
    "human_approval": "Stop before risky actions for a person",
    "multi_agent": "Handoffs, teams or orchestrators",
    "rag_heavy": "Many knowledge bases, retrieval is central",
    "typed_output": "Output parsed by code; must validate",
    "file_and_shell": "Edit files, run commands in a repo",
    "provider_neutral": "Must switch model providers freely",
}

# 0 = you build it yourself, 1 = supported, 2 = a core strength. Opinions, not benchmarks.
CAPABILITIES: dict[str, dict[str, int]] = {
    "no framework":      {"durable_state": 0, "human_approval": 1, "multi_agent": 1, "rag_heavy": 1,
                          "typed_output": 1, "file_and_shell": 0, "provider_neutral": 2},
    "LangGraph":         {"durable_state": 2, "human_approval": 2, "multi_agent": 2, "rag_heavy": 1,
                          "typed_output": 1, "file_and_shell": 0, "provider_neutral": 2},
    "OpenAI Agents SDK": {"durable_state": 1, "human_approval": 1, "multi_agent": 2, "rag_heavy": 1,
                          "typed_output": 2, "file_and_shell": 1, "provider_neutral": 1},
    "Claude Agent SDK":  {"durable_state": 1, "human_approval": 2, "multi_agent": 1, "rag_heavy": 0,
                          "typed_output": 1, "file_and_shell": 2, "provider_neutral": 0},
    "CrewAI":            {"durable_state": 1, "human_approval": 1, "multi_agent": 2, "rag_heavy": 1,
                          "typed_output": 1, "file_and_shell": 0, "provider_neutral": 2},
    "AutoGen AgentChat": {"durable_state": 1, "human_approval": 1, "multi_agent": 2, "rag_heavy": 0,
                          "typed_output": 1, "file_and_shell": 1, "provider_neutral": 2},
    "LlamaIndex":        {"durable_state": 1, "human_approval": 1, "multi_agent": 1, "rag_heavy": 2,
                          "typed_output": 1, "file_and_shell": 0, "provider_neutral": 2},
    "Pydantic AI":       {"durable_state": 1, "human_approval": 1, "multi_agent": 1, "rag_heavy": 0,
                          "typed_output": 2, "file_and_shell": 0, "provider_neutral": 2},
}
# Rough size of what you take on: 0 = nothing, 1 = one focused package, 2 = a large dependency tree or a CLI.
WEIGHT = {"no framework": 0, "LangGraph": 2, "OpenAI Agents SDK": 1, "Claude Agent SDK": 2, "CrewAI": 2,
          "AutoGen AgentChat": 2, "LlamaIndex": 2, "Pydantic AI": 1}


@dataclass
class Score:
    option: str
    total: float
    reasons: list[str] = field(default_factory=list)


def score(needs: list[str], avoid_deps: bool = False) -> list[Score]:
    unknown = set(needs) - set(NEEDS)
    if unknown:
        raise ValueError(f"unknown needs {sorted(unknown)}; choose from {sorted(NEEDS)}")
    out = []
    for option, caps in CAPABILITIES.items():
        s = Score(option, 0.0)
        for need in needs:
            s.total += caps[need]
            if caps[need] == 2:
                s.reasons.append(f"strong at {need}")
            elif caps[need] == 0:
                s.reasons.append(f"you build {need}")
        if avoid_deps:
            s.total -= WEIGHT[option]
            if WEIGHT[option]:
                s.reasons.append(f"dependency weight -{WEIGHT[option]}")
        out.append(s)
    return sorted(out, key=lambda s: (-s.total, WEIGHT[s.option]))


def recommend(needs: list[str], avoid_deps: bool = False, margin: float = 2.0) -> tuple[str, list[Score]]:
    """Skip frameworks unless the best one beats hand-rolled code by a clear margin."""
    ranked = score(needs, avoid_deps)
    baseline = next(s for s in ranked if s.option == "no framework")
    best = next(s for s in ranked if s.option != "no framework")
    if best.total - baseline.total < margin:
        return (f"skip the framework: the best option ({best.option}) beats a hand-rolled loop by only "
                f"{best.total - baseline.total:g} point(s)"), ranked
    return f"use {best.option}: +{best.total - baseline.total:g} over a hand-rolled loop", ranked


# ---------------------------------------------------------------- lock-in audit

FRAMEWORK_PACKAGES = {
    "langgraph": "LangGraph", "langchain": "LangChain", "langchain_core": "LangChain", "agents": "OpenAI Agents SDK",
    "claude_agent_sdk": "Claude Agent SDK", "crewai": "CrewAI", "autogen_agentchat": "AutoGen",
    "autogen_core": "AutoGen", "autogen_ext": "AutoGen", "llama_index": "LlamaIndex", "pydantic_ai": "Pydantic AI",
}


@dataclass
class Audit:
    files: int = 0
    framework_files: dict[str, list[str]] = field(default_factory=dict)     # file -> frameworks
    symbols: Counter = field(default_factory=Counter)                       # "LangGraph.StateGraph" -> uses
    portable_files: list[str] = field(default_factory=list)


def audit(root: Path) -> Audit:
    """Parse (never import or run) every .py file and record framework imports and the names used."""
    result = Audit()
    for path in sorted(root.rglob("*.py")):
        rel = str(path.relative_to(root))
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue
        result.files += 1
        imported: dict[str, str] = {}                          # local name -> "Framework.symbol"
        frameworks = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                fw = FRAMEWORK_PACKAGES.get(node.module.split(".")[0])
                if fw:
                    frameworks.add(fw)
                    for alias in node.names:
                        imported[alias.asname or alias.name] = f"{fw}.{alias.name}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    fw = FRAMEWORK_PACKAGES.get(alias.name.split(".")[0])
                    if fw:
                        frameworks.add(fw)
                        imported[(alias.asname or alias.name).split(".")[0]] = f"{fw}.*"
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in imported:
                result.symbols[imported[node.id]] += 1
        if frameworks:
            result.framework_files[rel] = sorted(frameworks)
        else:
            result.portable_files.append(rel)
    return result


EXAMPLES = {
    "support bot: refunds need approval, must survive restarts": (["durable_state", "human_approval"], False),
    "one agent that extracts typed invoices, few dependencies": (["typed_output"], True),
    "automation that edits a repo and runs tests": (["file_and_shell", "human_approval"], False),
}


def print_recommendation(title: str, needs: list[str], avoid_deps: bool) -> None:
    verdict, ranked = recommend(needs, avoid_deps)
    print(f"{title}\n  needs: {', '.join(needs)}{' + avoid dependencies' if avoid_deps else ''}")
    for s in ranked[:3]:
        print(f"    {s.total:>4g}  {s.option:<18} {'; '.join(s.reasons)}")
    print(f"  -> {verdict}\n")


def print_audit(root: Path) -> None:
    a = audit(root)
    print(f"lock-in audit of {root.name}/: {a.files} Python files")
    for f, fws in a.framework_files.items():
        print(f"  {f:<14} imports {', '.join(fws)}")
    print(f"  portable (no framework imports): {', '.join(a.portable_files) or 'none'}")
    print(f"  framework surface: {len(a.symbols)} symbols, {sum(a.symbols.values())} uses")
    for sym, n in a.symbols.most_common():
        print(f"    {n:>3}  {sym}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--needs", nargs="*", choices=sorted(NEEDS))
    ap.add_argument("--avoid-deps", action="store_true")
    ap.add_argument("--audit", type=Path)
    args = ap.parse_args()
    if args.needs:
        print_recommendation("your project", args.needs, args.avoid_deps)
    elif not args.audit:
        for title, (needs, avoid) in EXAMPLES.items():
            print_recommendation(title, needs, avoid)
    print_audit(args.audit or Path(__file__).parent / "sample_app")
