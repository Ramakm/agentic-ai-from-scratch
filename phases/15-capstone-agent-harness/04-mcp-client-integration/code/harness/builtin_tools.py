"""File tools for a workspace: list, read, search, write, edit. Every path is jailed to the workspace root."""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from .tools import Tool, ToolRegistry, schema_from_function

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".harness"}


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.read_paths: set[Path] = set()     # edit requires a read first, so the model edits what it saw

    def resolve(self, path: str) -> Path:
        """A path inside the workspace, or ValueError. Resolving first defeats `..` and symlink escapes."""
        p = (self.root / path).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError(f"{path!r} is outside the workspace")
        return p

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.root)) or "."

    def walk(self, start: Path):
        for dirpath, dirnames, filenames in os.walk(start):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(filenames):
                yield Path(dirpath) / name

    # ---- tools (docstring first line = description; `arg: text` lines describe arguments)
    def list_files(self, path: str = ".", pattern: str = "*") -> str:
        """List files under a directory, recursively.

        path: directory relative to the workspace root
        pattern: glob on the file name, e.g. *.py
        """
        start = self.resolve(path)
        files = [self.rel(f) for f in self.walk(start) if fnmatch.fnmatch(f.name, pattern)]
        if not files:
            return f"no files matching {pattern!r} under {path}"
        more = f"\n... and {len(files) - 200} more" if len(files) > 200 else ""
        return "\n".join(files[:200]) + more

    def read_file(self, path: str, offset: int = 1, limit: int = 200) -> str:
        """Read a text file with line numbers. Use offset and limit to page through long files.

        path: file relative to the workspace root
        offset: first line to show, starting at 1
        limit: how many lines to show
        """
        p = self.resolve(path)
        lines = p.read_text(errors="replace").splitlines()
        self.read_paths.add(p)
        start = max(offset, 1)
        chunk = lines[start - 1: start - 1 + max(limit, 1)]
        body = "\n".join(f"{i:>5}  {line}" for i, line in enumerate(chunk, start))
        end = start + len(chunk) - 1
        tail = f"\n[lines {start}-{end} of {len(lines)}; use offset={end + 1} for more]" if end < len(lines) else ""
        return (body or "(empty file)") + tail

    def search(self, pattern: str, path: str = ".", glob: str = "*") -> str:
        """Search file contents with a regular expression. Returns file:line: text matches.

        pattern: Python regular expression
        path: directory to search
        glob: only search files whose name matches, e.g. *.py
        """
        rx = re.compile(pattern)
        hits = []
        for f in self.walk(self.resolve(path)):
            if not fnmatch.fnmatch(f.name, glob):
                continue
            try:
                for i, line in enumerate(f.read_text(errors="strict").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{self.rel(f)}:{i}: {line.strip()[:160]}")
            except (UnicodeDecodeError, OSError):
                continue
            if len(hits) >= 100:
                break
        return "\n".join(hits[:100]) if hits else f"no matches for {pattern!r}"

    def write_file(self, path: str, content: str) -> str:
        """Create or overwrite a file with the given content.

        path: file relative to the workspace root
        content: the full new content
        """
        p = self.resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        self.read_paths.add(p)
        return f"wrote {self.rel(p)} ({len(content.splitlines())} lines)"

    def edit_file(self, path: str, old: str, new: str) -> str:
        """Replace one exact, unique snippet in a file. Read the file first.

        path: file relative to the workspace root
        old: the exact text to replace, unique in the file
        new: the replacement text
        """
        p = self.resolve(path)
        if p not in self.read_paths:
            raise ValueError(f"read {path} before editing it")
        text = p.read_text()
        n = text.count(old)
        if n != 1:
            raise ValueError(f"`old` must appear exactly once in {path}, found {n} times"
                             + ("; include more surrounding lines" if n > 1 else "; re-read the file"))
        p.write_text(text.replace(old, new, 1))
        return f"edited {self.rel(p)}"


def file_tools(ws: Workspace, registry: ToolRegistry | None = None) -> ToolRegistry:
    """Register the workspace's file tools. Reads are read_only; writes are not."""
    reg = registry or ToolRegistry()
    for fn, ro in [(ws.list_files, True), (ws.read_file, True), (ws.search, True),
                   (ws.write_file, False), (ws.edit_file, False)]:
        desc = (fn.__doc__ or "").strip().split("\n\n")[0]
        reg.add(Tool(fn.__name__, desc, schema_from_function(fn), lambda a, fn=fn: fn(**a),
                     read_only=ro, match_arg="path"))
    return reg
