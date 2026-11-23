"""File tools a model can use well: paged reads with line numbers, capped search, exact-match
edits with helpful failures, a read-before-edit guard, diffs, and undo.

    python3 main.py                  # offline: a scripted session that renames a function
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen2.5-coder python3 main.py

Standard library only.
"""
from __future__ import annotations

import copy
import difflib
import fnmatch
import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
MAX_LINE = 300          # characters per line shown
MAX_READ = 400          # lines per read
MAX_HITS = 30           # search results shown


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass
class FileTools:
    root: Path
    seen: dict[str, str] = field(default_factory=dict)            # path -> digest at last read
    history: dict[str, list[str]] = field(default_factory=dict)   # path -> previous contents (for undo)

    # -------------------------------------------------- paths
    def _path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in (p, *p.parents):
            raise PermissionError(f"{rel!r} is outside the workspace")
        return p

    def _files(self, pattern: str = "*"):
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if p.is_file() and not SKIP_DIRS & set(rel.parts) and fnmatch.fnmatch(str(rel), pattern):
                yield p, str(rel)

    # -------------------------------------------------- read
    def read_file(self, path: str, offset: int = 1, limit: int = MAX_READ) -> str:
        p = self._path(path)
        if not p.exists():
            close = difflib.get_close_matches(path, [r for _, r in self._files()], n=3)
            return f"error: {path} does not exist." + (f" Did you mean: {', '.join(close)}?" if close else "")
        raw = p.read_bytes()
        if b"\0" in raw[:4096]:
            return f"error: {path} looks binary ({len(raw)} bytes); not shown"
        text = raw.decode(errors="replace")
        self.seen[path] = _digest(text)
        lines = text.splitlines()
        offset, limit = max(1, offset), max(1, min(limit, MAX_READ))
        chunk = lines[offset - 1: offset - 1 + limit]
        out = [f"{i:>5}\t{line[:MAX_LINE]}{' …[line truncated]' if len(line) > MAX_LINE else ''}"
               for i, line in enumerate(chunk, offset)]
        end = offset + len(chunk) - 1
        if end < len(lines):
            out.append(f"… {len(lines) - end} more lines. Call read_file with offset={end + 1} to continue.")
        return "\n".join(out) or f"(empty file: {path})"

    # -------------------------------------------------- search
    def search(self, pattern: str, glob: str = "*", max_results: int = MAX_HITS) -> str:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return f"error: invalid regex {pattern!r}: {exc}. Escape special characters like ( ) [ ] ."
        hits = []
        for p, rel in self._files(glob):
            try:
                text = p.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}: {line.strip()[:MAX_LINE]}")
        if not hits:
            return f"no matches for {pattern!r} in {glob}"
        shown = hits[:max_results]
        more = len(hits) - len(shown)
        return "\n".join(shown) + (f"\n… {more} more matches. Narrow the pattern or the glob." if more else "")

    def find_files(self, glob: str) -> str:
        found = [rel for _, rel in self._files(glob)]
        return "\n".join(found[:200]) or f"no files match {glob!r}"

    # -------------------------------------------------- edit
    def edit_file(self, path: str, old: str, new: str, replace_all: bool = False) -> str:
        p = self._path(path)
        if not p.exists():
            return f"error: {path} does not exist. Use create_file for new files."
        text = p.read_text()
        if path not in self.seen:
            return f"error: read {path} before editing it."
        if self.seen[path] != _digest(text):
            return f"error: {path} changed since you last read it. Read it again before editing."
        if old == new:
            return "error: old and new are identical; nothing to do."
        count = text.count(old)
        if count == 0:
            return f"error: `old` was not found in {path}." + self._hint(text, old)
        if count > 1 and not replace_all:
            lines = [str(i) for i, line in enumerate(text.splitlines(), 1) if old.splitlines()[0] in line]
            return (f"error: `old` appears {count} times in {path} (lines {', '.join(lines)}). "
                    "Include more surrounding lines to make it unique, or pass replace_all=true.")
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        self.history.setdefault(path, []).append(text)
        p.write_text(updated)
        self.seen[path] = _digest(updated)
        return f"edited {path} ({count if replace_all else 1} replacement(s))\n" + self._diff(path, text, updated)

    def _hint(self, text: str, old: str) -> str:
        """The commonest failure is whitespace or a stale copy. Show the closest real line."""
        first = old.strip().splitlines()[0] if old.strip() else old
        lines = text.splitlines()
        stripped = [line.strip() for line in lines]
        if first.strip() in stripped:
            n = stripped.index(first.strip()) + 1
            return f" Line {n} matches if you ignore indentation: {lines[n - 1]!r}. Copy whitespace exactly."
        close = difflib.get_close_matches(first.strip(), stripped, n=1, cutoff=0.6)
        if close:
            n = stripped.index(close[0]) + 1
            return f" Closest line is {n}: {lines[n - 1]!r}. Read the file again and copy the text exactly."
        return " Read the file again; it may have changed."

    @staticmethod
    def _diff(path: str, before: str, after: str) -> str:
        return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                            f"a/{path}", f"b/{path}", n=1)).rstrip()

    def create_file(self, path: str, content: str, overwrite: bool = False) -> str:
        p = self._path(path)
        if p.exists() and not overwrite:
            return f"error: {path} already exists. Use edit_file, or pass overwrite=true."
        if p.exists():
            self.history.setdefault(path, []).append(p.read_text())
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        self.seen[path] = _digest(content)
        return f"wrote {path} ({len(content.splitlines())} lines)"

    def undo_edit(self, path: str) -> str:
        if not self.history.get(path):
            return f"error: no edits to undo for {path}"
        previous = self.history[path].pop()
        self._path(path).write_text(previous)
        self.seen[path] = _digest(previous)
        return f"restored {path} to its state before the last edit"

    def call(self, name: str, args: dict) -> str:
        fn = getattr(self, name, None) if name in TOOL_NAMES else None
        if not fn:
            return f"error: unknown tool {name!r}"
        try:
            return fn(**args)
        except TypeError as exc:
            return f"error: bad arguments for {name}: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"error: {type(exc).__name__}: {exc}"


TOOL_NAMES = ["read_file", "search", "find_files", "edit_file", "create_file", "undo_edit"]

# ---------------------------------------------------------------- a scripted session

DEMO_FILES = {
    "shop/pricing.py": "def calc_total(items):\n    return sum(i['price'] * i['qty'] for i in items)\n",
    "shop/cart.py": "from shop.pricing import calc_total\n\n\ndef checkout(cart):\n    total = calc_total(cart)\n"
                    "    return {'total': total}\n",
    "shop/report.py": "from shop.pricing import calc_total\n\n\ndef summary(orders):\n"
                      "    return [calc_total(o) for o in orders]\n",
    "node_modules/lib/index.js": "calc_total = 1  // vendored: search must skip this\n",
}


def make_workspace() -> Path:
    root = Path(tempfile.mkdtemp(prefix="file-tools-"))
    for rel, text in DEMO_FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


def step(name: str, **args) -> dict:
    return {"name": name, "args": args}


DEMO_STEPS = [
    step("search", pattern=r"calc_total\("),
    step("edit_file", path="shop/cart.py", old="calc_total(cart)", new="order_total(cart)"),   # not read yet
    step("read_file", path="shop/cart.py"),
    step("edit_file", path="shop/cart.py", old="calc_total", new="order_total"),               # ambiguous
    step("edit_file", path="shop/cart.py", old="calc_total", new="order_total", replace_all=True),
    step("read_file", path="shop/pricing.py"),
    step("edit_file", path="shop/pricing.py", old="def calc_total(items):\n  return",
         new="def order_total(items):\n    return"),                                              # wrong indentation
    step("edit_file", path="shop/pricing.py", old="def calc_total(items):", new="def order_total(items):"),
    step("read_file", path="shop/report.py"),
    step("edit_file", path="shop/report.py", old="calc_total", new="order_total", replace_all=True),
    step("search", pattern=r"calc_total"),
]


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> Callable[[list, list], dict]:
    def call(messages: list, schemas: list) -> dict:
        body = json.dumps({"model": model, "messages": messages, "tools": schemas}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
    return call


SCHEMAS = [{"type": "function", "function": {"name": n, "description": (getattr(FileTools, n).__doc__ or n),
            "parameters": {"type": "object", "properties": props, "required": req}}} for n, props, req in [
    ("read_file", {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["path"]),
    ("search", {"pattern": {"type": "string"}, "glob": {"type": "string"}}, ["pattern"]),
    ("find_files", {"glob": {"type": "string"}}, ["glob"]),
    ("edit_file", {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
                   "replace_all": {"type": "boolean"}}, ["path", "old", "new"]),
    ("create_file", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    ("undo_edit", {"path": {"type": "string"}}, ["path"]),
]]


def run_with_model(task: str, llm: Callable[[list, list], dict], tools: FileTools, max_steps: int = 20) -> str:
    messages = [{"role": "system", "content": "You edit code with the file tools. Read before editing."},
                {"role": "user", "content": task}]
    for _ in range(max_steps):
        reply = llm(messages, SCHEMAS)
        messages.append(reply)
        if not reply.get("tool_calls"):
            return reply.get("content") or ""
        for c in reply["tool_calls"]:
            out = tools.call(c["function"]["name"], json.loads(c["function"].get("arguments") or "{}"))
            print(f"> {c['function']['name']} -> {out.splitlines()[0] if out else ''}")
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    return "(step budget spent)"


if __name__ == "__main__":
    tools = FileTools(make_workspace())
    base = os.environ.get("AGENT_BASE_URL")
    if base:
        llm = openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "qwen2.5-coder"), os.environ.get("AGENT_API_KEY", ""))
        print(run_with_model("Rename calc_total to order_total everywhere.", llm, tools))
    else:
        for s in copy.deepcopy(DEMO_STEPS):
            out = tools.call(s["name"], s["args"])
            print(f"> {s['name']}({', '.join(f'{k}={v!r}' for k, v in s['args'].items())})")
            print("  " + out.replace("\n", "\n  ") + "\n")
