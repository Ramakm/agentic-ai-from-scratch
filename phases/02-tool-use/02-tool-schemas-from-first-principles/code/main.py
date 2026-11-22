"""Tool schemas from first principles.

Turn a typed Python function into the JSON Schema a model sees, validate the
arguments the model sends back, and emit both OpenAI and Anthropic formats.
Standard library only.
"""
from __future__ import annotations

import inspect
import json
import re
import types
import typing
from typing import Any, Callable, Literal, Optional

PRIMITIVES = {str: "string", int: "integer", float: "number", bool: "boolean"}


# ---------------------------------------------------------------- schema

def type_to_schema(tp: Any) -> dict:
    """Map a Python type hint to a JSON Schema fragment."""
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if tp in PRIMITIVES:
        return {"type": PRIMITIVES[tp]}
    if origin is Literal:
        kinds = {PRIMITIVES[type(a)] for a in args}
        return {"type": kinds.pop() if len(kinds) == 1 else sorted(kinds), "enum": list(args)}
    if origin in (list, tuple, set):
        return {"type": "array", "items": type_to_schema(args[0]) if args else {}}
    if origin is dict:
        return {"type": "object"}
    if origin in (typing.Union, types.UnionType):
        non_null = [a for a in args if a is not type(None)]
        if len(non_null) == 1:            # Optional[X] -> X, made non-required by its default
            return type_to_schema(non_null[0])
        return {"anyOf": [type_to_schema(a) for a in non_null]}
    raise TypeError(f"unsupported type for a tool parameter: {tp!r}")


def parse_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """Split a Google-style docstring into a summary and per-argument descriptions."""
    doc = inspect.cleandoc(doc or "")
    summary, _, rest = doc.partition("\nArgs:")
    params = dict(re.findall(r"^\s+(\w+)(?:\s*\([^)]*\))?:\s*(.+)$", rest, flags=re.M))
    return summary.strip(), params


def function_to_tool(fn: Callable[..., Any]) -> dict:
    """Build a provider-neutral tool definition from a typed function."""
    hints = typing.get_type_hints(fn)
    summary, arg_docs = parse_docstring(fn.__doc__ or "")
    if not summary:
        raise ValueError(f"{fn.__name__} needs a docstring: the model reads it to decide when to call")
    props, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        if name not in hints:
            raise TypeError(f"{fn.__name__}.{name} needs a type hint")
        prop = type_to_schema(hints[name])
        if name in arg_docs:
            prop["description"] = arg_docs[name]
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            prop["default"] = param.default
        props[name] = prop
    return {"name": fn.__name__, "description": summary,
            "parameters": {"type": "object", "properties": props,
                           "required": required, "additionalProperties": False}}


def to_openai(tool: dict) -> dict:
    return {"type": "function", "function": tool}


def to_anthropic(tool: dict) -> dict:
    return {"name": tool["name"], "description": tool["description"], "input_schema": tool["parameters"]}


# ---------------------------------------------------------------- validation

JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
              "array": list, "object": dict}


def _type_ok(value: Any, kind: str) -> bool:
    if kind in ("integer", "number") and isinstance(value, bool):
        return False                      # bool is a subclass of int; JSON disagrees
    return isinstance(value, JSON_TYPES[kind])


def validate(schema: dict, value: Any, path: str = "args") -> list[str]:
    """Return a list of human-readable problems. Empty list means valid."""
    if "anyOf" in schema:
        return [] if any(not validate(s, value, path) for s in schema["anyOf"]) else [f"{path}: matches no allowed type"]
    errors: list[str] = []
    kinds = schema.get("type")
    if kinds:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if not any(_type_ok(value, k) for k in kinds):
            return [f"{path}: expected {' or '.join(kinds)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}, got {value!r}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors += validate(schema["items"], item, f"{path}[{i}]")
    if isinstance(value, dict) and "properties" in schema:
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        for key, item in value.items():
            if key in schema["properties"]:
                errors += validate(schema["properties"][key], item, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: unknown argument")
    return errors


def call_tool(fn: Callable[..., Any], raw_arguments: str) -> str:
    """Parse, validate, then call. Every failure is a string the model can act on."""
    tool = function_to_tool(fn)
    try:
        args = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        return f"error: arguments are not valid JSON ({exc.msg})"
    problems = validate(tool["parameters"], args)
    if problems:
        return "error: invalid arguments: " + "; ".join(problems)
    return json.dumps(fn(**args))


# ---------------------------------------------------------------- demo

def search_flights(origin: str, destination: str, date: str,
                   cabin: Literal["economy", "business"] = "economy",
                   max_stops: Optional[int] = None, airlines: Optional[list[str]] = None) -> dict:
    """Search one-way flights between two airports.

    Args:
        origin: IATA code of the departure airport, e.g. BLR.
        destination: IATA code of the arrival airport, e.g. SFO.
        date: Departure date as YYYY-MM-DD.
        cabin: Cabin class.
        max_stops: Maximum number of stops. Omit for any.
        airlines: Only include these airline codes.
    """
    return {"results": 3, "route": f"{origin}->{destination}", "date": date, "cabin": cabin}


if __name__ == "__main__":
    tool = function_to_tool(search_flights)
    print("OpenAI format:\n" + json.dumps(to_openai(tool), indent=2))
    print("\nAnthropic format keys:", list(to_anthropic(tool)))
    for raw in ['{"origin": "BLR", "destination": "SFO", "date": "2026-12-01"}',
                '{"origin": "BLR", "date": "2026-12-01", "cabin": "first"}',
                '{"origin": "BLR", "destination": "SFO", "date": "2026-12-01", "max_stops": "1", "seat": "aisle"}',
                '{origin: BLR}']:
        print(f"\nmodel sent: {raw}\nobservation: {call_tool(search_flights, raw)}")
