"""Skills and SKILL.md: package know-how as folders an agent loads only when it needs them.
Level 1: every skill's name + description sit in the system prompt. Level 2: the agent
calls load_skill to read one SKILL.md body. Level 3: it reads the skill's extra files on demand.

    python3 main.py                  # discovers this repo's own skills/ folder, scripted model
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen2.5 python3 main.py

Standard library only.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LLM = Callable[[list, list], dict]
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """The YAML subset SKILL.md files use: `key: value`, plus `key: >` (folded) and `key: |` (literal) blocks."""
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with '---' frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("frontmatter is not closed with '---'")
    meta, key, mode, buf = {}, None, "", []

    def flush() -> None:
        if key and mode:
            meta[key] = (" ".join(b.strip() for b in buf) if mode == ">" else "\n".join(b.strip() for b in buf)).strip()

    for line in text[4:end].splitlines():
        if mode and (line.startswith("  ") or not line.strip()):
            buf.append(line)
            continue
        flush()
        mode, buf = "", []
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        if value in (">", "|", ">-", "|-"):
            mode = value[0]
        else:
            meta[key] = value.strip("'\"")
    flush()
    return meta, text[end + 4:].lstrip("\n")


@dataclass
class Skill:
    name: str
    description: str
    body: str
    folder: Path
    files: list[str] = field(default_factory=list)


def validate(meta: dict[str, str], folder: Path) -> list[str]:
    """Rules from the Agent Skills format: a short lowercase-hyphen name that matches the folder, and a
    description that says what the skill does and when to use it (it's all the model sees up front)."""
    problems = []
    name, desc = meta.get("name", ""), meta.get("description", "")
    if not name:
        problems.append("missing 'name'")
    elif not NAME_RE.match(name) or len(name) > 64:
        problems.append(f"name {name!r} must be lowercase letters, digits and hyphens, at most 64 characters")
    elif name != folder.name:
        problems.append(f"name {name!r} doesn't match its folder {folder.name!r}")
    if not desc:
        problems.append("missing 'description'")
    elif len(desc) > 1024:
        problems.append(f"description is {len(desc)} characters; keep it under 1024")
    elif not re.search(r"\b(use when|use it when|trigger|when (?:the|a|someone|you))", desc, re.I):
        problems.append("description doesn't say WHEN to use the skill (add 'Use when …' or trigger phrases)")
    return problems


@dataclass
class SkillRegistry:
    skills: dict[str, Skill] = field(default_factory=dict)
    rejected: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def discover(cls, root: Path) -> "SkillRegistry":
        reg = cls()
        for md in sorted(root.glob("*/SKILL.md")):
            try:
                meta, body = parse_frontmatter(md.read_text())
            except ValueError as exc:
                reg.rejected[md.parent.name] = [str(exc)]
                continue
            problems = validate(meta, md.parent)
            if any("missing" in p or "must be" in p for p in problems):
                reg.rejected[md.parent.name] = problems
                continue
            if problems:
                reg.rejected[md.parent.name] = problems          # warnings: loaded anyway, but reported
            extra = sorted(str(p.relative_to(md.parent)) for p in md.parent.rglob("*") if p.is_file() and p != md)
            reg.skills[meta["name"]] = Skill(meta["name"], meta["description"], body, md.parent, extra)
        return reg

    # level 1: always in context
    def catalog(self) -> str:
        return "\n".join(f"- {s.name}: {s.description}" for s in self.skills.values())

    # level 2: on demand
    def load_skill(self, name: str) -> str:
        s = self.skills.get(name)
        if not s:
            return f"error: no skill {name!r}. Available: {', '.join(self.skills)}"
        files = f"\n\nBundled files you can read with read_skill_file: {', '.join(s.files)}" if s.files else ""
        return s.body + files

    # level 3: only the file that's needed
    def read_skill_file(self, name: str, path: str) -> str:
        s = self.skills.get(name)
        if not s:
            return f"error: no skill {name!r}"
        p = (s.folder / path).resolve()
        if s.folder.resolve() not in p.parents or not p.is_file():
            return f"error: {path!r} is not a file in skill {name!r}"
        return p.read_text()


SCHEMAS = [
    {"type": "function", "function": {"name": "load_skill", "description": "Load a skill's full instructions.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "read_skill_file", "description": "Read a file bundled with a skill.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "path": {"type": "string"}},
                    "required": ["name", "path"]}}},
]


def system_prompt(reg: SkillRegistry) -> str:
    return ("You are a helpful agent. These skills are available. If one matches the request, call load_skill "
            f"with its name before answering, then follow its instructions.\n\nSkills:\n{reg.catalog()}")


def run(task: str, llm: LLM, reg: SkillRegistry, max_steps: int = 6) -> tuple[str, list[str]]:
    messages = [{"role": "system", "content": system_prompt(reg)}, {"role": "user", "content": task}]
    loaded = []
    for _ in range(max_steps):
        reply = llm(messages, SCHEMAS)
        messages.append(reply)
        if not reply.get("tool_calls"):
            return reply.get("content") or "", loaded
        for c in reply["tool_calls"]:
            args = json.loads(c["function"].get("arguments") or "{}")
            if c["function"]["name"] == "load_skill":
                out = reg.load_skill(args.get("name", ""))
                loaded.append(args.get("name", ""))
            else:
                out = reg.read_skill_file(args.get("name", ""), args.get("path", ""))
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    return "", loaded


def tokens(text: str) -> int:
    return len(text) // 4


# ---------------------------------------------------------------- demo

REPO_SKILLS = Path(__file__).resolve().parents[4] / "skills"

SAMPLE = {
    "pdf-report/SKILL.md": "---\nname: pdf-report\ndescription: >\n  Turn a CSV into a one-page PDF report with a chart.\n"
                           "  Use when someone asks for a PDF summary of tabular data.\n---\n\n# PDF report\n\n"
                           "1. Read the CSV.\n2. Follow STYLE.md for fonts and colours.\n",
    "pdf-report/STYLE.md": "Fonts: Inter 11pt. Colours: #1f2937 text, #2563eb accents.\n",
    "Bad_Name/SKILL.md": "---\nname: Bad_Name\ndescription: does stuff\n---\nbody\n",
    "vague/SKILL.md": "---\nname: vague\ndescription: Helps with documents.\n---\nbody\n",
}


def make_sample_skills() -> Path:
    root = Path(tempfile.mkdtemp(prefix="skills-"))
    for rel, text in SAMPLE.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


def _call(i: str, name: str, args: dict) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


DEMO_SCRIPT = [
    _call("1", "load_skill", {"name": "debug-my-agent"}),
    {"role": "assistant", "content": "Following the debug-my-agent skill: paste your agent's trace and I'll start "
                                     "with the stop condition, since a loop that never ends usually lacks one."},
]


def scripted_llm(script: list[dict]) -> LLM:
    replies = iter(copy.deepcopy(script))
    return lambda messages, schemas: next(replies)


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list, schemas: list) -> dict:
        body = json.dumps({"model": model, "messages": messages, "tools": schemas}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
    return call


if __name__ == "__main__":
    root = REPO_SKILLS if REPO_SKILLS.is_dir() else make_sample_skills()
    reg = SkillRegistry.discover(root)
    print(f"discovered {len(reg.skills)} skills in {root.name}/")
    always = tokens(system_prompt(reg))
    everything = always + sum(tokens(s.body) for s in reg.skills.values())
    print(f"  level 1 (names + descriptions, always in context): ~{always} tokens")
    print(f"  all bodies loaded up front instead:                ~{everything} tokens")
    for name, problems in reg.rejected.items():
        print(f"  note on {name}: {'; '.join(problems)}")
    base = os.environ.get("AGENT_BASE_URL")
    llm = (openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "qwen2.5"), os.environ.get("AGENT_API_KEY", ""))
           if base else scripted_llm(DEMO_SCRIPT))
    task = "My agent keeps calling the same tool forever and never answers. Help?"
    answer, loaded = run(task, llm, reg)
    print(f"\ntask: {task}\nloaded skills: {loaded} (+~{sum(tokens(reg.skills[n].body) for n in loaded if n in reg.skills)} tokens)")
    print(f"answer: {answer}")
    print("\nvalidating sample skills:")
    sample = SkillRegistry.discover(make_sample_skills())
    print(f"  loaded: {list(sample.skills)}")
    for name, problems in sample.rejected.items():
        print(f"  {name}: {'; '.join(problems)}")
    print(f"  level 3: pdf-report bundles {sample.skills['pdf-report'].files}; "
          f"read on demand -> {sample.read_skill_file('pdf-report', 'STYLE.md').strip()!r}")
