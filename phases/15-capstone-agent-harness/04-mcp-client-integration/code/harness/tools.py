"""The tool registry: what the model can call, the schemas it sees, and one safe way to call them.

Every failure (unknown tool, bad JSON, wrong arguments, an exception) comes back as a ToolResult
with error=True. The loop shows it to the model as an observation; nothing here crashes the run.
"""
from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, replace
from typing import Any, Callable

JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}
PY_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
NAME_OK = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@dataclass
class ToolResult:
    text: str
    error: bool = False


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict                     # JSON Schema for the arguments object
    fn: Callable[[dict], Any]            # takes the parsed arguments dict
    read_only: bool = False              # no side effects: safe in plan mode, safe for explorers
    source: str = "builtin"              # "builtin", "mcp:<server>", "subagent", ...
    match_arg: str | None = None         # the argument permission rules match against ("path", "command")

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}


def schema_from_function(fn: Callable) -> dict:
    """Parameters schema from a signature. Docstring lines like `path: file to read` describe arguments."""
    docs = dict(re.findall(r"^\s*(\w+):\s*(.+)$", fn.__doc__ or "", re.M))
    props, required = {}, []
    for name, p in inspect.signature(fn).parameters.items():
        ann = p.annotation
        if isinstance(ann, str):              # `from __future__ import annotations` makes them strings
            ann = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}.get(ann)
        prop: dict = {"type": JSON_TYPES.get(ann, "string")}
        if name in docs:
            prop["description"] = docs[name]
        if p.default is inspect.Parameter.empty:
            required.append(name)
        else:
            prop["default"] = p.default
        props[name] = prop
    return {"type": "object", "properties": props, "required": required}


def validate(args: Any, schema: dict) -> str | None:
    """Check arguments against the schema's top level. Returns a message for the model, or None."""
    if not isinstance(args, dict):
        return "arguments must be a JSON object"
    props = schema.get("properties", {})
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        return f"missing required argument(s): {', '.join(missing)}"
    extra = [k for k in args if k not in props]
    if extra and props and schema.get("additionalProperties") is not True:
        return f"unknown argument(s): {', '.join(extra)}; expected: {', '.join(props)}"
    for k, v in args.items():
        want = props.get(k, {}).get("type")
        py = PY_TYPES.get(want)
        wrong_type = py is not None and not isinstance(v, py)
        if wrong_type or (want in ("integer", "number") and isinstance(v, bool)):
            return f"argument {k!r} should be {want}, got {type(v).__name__}"
        if "enum" in props.get(k, {}) and v not in props[k]["enum"]:
            return f"argument {k!r} must be one of {props[k]['enum']}"
    return None


def parse_args(raw: Any) -> tuple[dict | None, str | None]:
    """Tool-call arguments arrive as a JSON string (sometimes already a dict, sometimes empty)."""
    if isinstance(raw, dict):
        return raw, None
    if raw in (None, ""):
        return {}, None
    try:
        val = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        return None, f"arguments were not valid JSON ({getattr(e, 'msg', e)}): {str(raw)[:120]}"
    return (val, None) if isinstance(val, dict) else (None, "arguments must be a JSON object")


class ToolRegistry:
    def __init__(self, max_output_chars: int = 6000) -> None:
        self.tools: dict[str, Tool] = {}
        self.max_output_chars = max_output_chars

    # ---- registering
    def add(self, tool: Tool) -> Tool:
        if not NAME_OK.match(tool.name):
            raise ValueError(f"tool name {tool.name!r} must match {NAME_OK.pattern}")
        if tool.name in self.tools:
            raise ValueError(f"tool {tool.name!r} is already registered (from {self.tools[tool.name].source})")
        self.tools[tool.name] = tool
        return tool

    def tool(self, fn: Callable | None = None, *, read_only: bool = False, name: str | None = None,
             match_arg: str | None = None):
        """Decorator: @registry.tool or @registry.tool(read_only=True). The docstring's first line is the description."""
        def wrap(f: Callable) -> Callable:
            desc = (f.__doc__ or "").strip().split("\n\n")[0].strip()
            self.add(Tool(name or f.__name__, desc, schema_from_function(f), lambda a, f=f: f(**a),
                          read_only=read_only, match_arg=match_arg))
            return f
        return wrap(fn) if fn else wrap

    def subset(self, keep: Callable[[Tool], bool]) -> "ToolRegistry":
        """A new registry with only some tools, e.g. the read-only ones for an explorer subagent."""
        out = ToolRegistry(self.max_output_chars)
        out.tools = {n: t for n, t in self.tools.items() if keep(t)}
        return out

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self.tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self.tools

    def __len__(self) -> int:
        return len(self.tools)

    # ---- calling
    def call(self, name: str, args: Any) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(f"error: unknown tool {name!r}. Available: {', '.join(sorted(self.tools))}", True)
        parsed, err = parse_args(args)
        if err is None:
            err = validate(parsed, tool.parameters)
        if err:
            return ToolResult(f"error: {err}", True)
        try:
            out = tool.fn(parsed)
        except Exception as e:  # noqa: BLE001 - the model needs to see it, the run must go on
            return ToolResult(f"error: {type(e).__name__}: {e}", True)
        if isinstance(out, ToolResult):
            return replace(out, text=self.clip(out.text))
        return ToolResult(self.clip(out if isinstance(out, str) else json.dumps(out, default=str)))

    def clip(self, text: str) -> str:
        """Huge outputs flood the context. Keep the head and tail, and say what was cut."""
        n = self.max_output_chars
        if len(text) <= n:
            return text
        head, tail = text[: n * 3 // 4], text[-(n // 4):]
        return f"{head}\n[... {len(text) - len(head) - len(tail):,} characters cut ...]\n{tail}"


__all__ = ["Tool", "ToolRegistry", "ToolResult", "parse_args", "schema_from_function", "validate"]
