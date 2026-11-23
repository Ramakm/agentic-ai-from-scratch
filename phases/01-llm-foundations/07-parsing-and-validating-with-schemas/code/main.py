"""Parsing and validating with schemas: from "it's JSON" to "it's a correct, typed Python object".

Three layers:
  1. shape       - a JSON Schema validator with paths in every error ($.items[1].qty)
  2. types       - turn the dict into dataclasses using type hints (nested, Optional, list, Literal)
  3. meaning     - rules a schema can't express (the total must equal the sum of the line items)
Then a loop: validate -> feed the errors back -> let the model fix its own output.

    python3 main.py             # offline: errors at every layer, and a scripted repair loop
    python3 main.py --live 3    # live: 5 receipts x 3 runs, first-try vs after retries
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
import typing
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

# ---------------------------------------------------------------- layer 1: JSON Schema with paths


def validate(value: Any, schema: dict, path: str = "$") -> list[str]:
    errors: list[str] = []
    t = schema.get("type")
    kinds = t if isinstance(t, list) else [t] if t else []
    if kinds and not any(is_type(value, k) for k in kinds):
        return [f"{path}: expected {' or '.join(kinds)}, got {json_type(value)}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}, got {value!r}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: must be at least {schema['minLength']} characters")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: must match {schema['pattern']}, got {value!r}")
    if is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}, got {value}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: must be <= {schema['maximum']}, got {value}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        for i, item in enumerate(value):
            errors += validate(item, schema.get("items", {}), f"{path}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        errors += [f"{path}.{k}: required" for k in schema.get("required", []) if k not in value]
        for k, v in value.items():
            if k in props:
                errors += validate(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{k}: not allowed")
    return errors


def is_type(v: Any, kind: str) -> bool:
    if isinstance(v, bool):
        return kind == "boolean"
    return {"string": isinstance(v, str), "integer": isinstance(v, int),
            "number": isinstance(v, (int, float)), "object": isinstance(v, dict),
            "array": isinstance(v, list), "null": v is None}.get(kind, False)


def json_type(v: Any) -> str:
    for k in ("boolean", "integer", "number", "string", "array", "object", "null"):
        if is_type(v, k):
            return k
    return type(v).__name__

# ---------------------------------------------------------------- layer 2: typed objects


@dataclass
class Item:
    name: str
    qty: int
    unit_price: float


@dataclass
class Receipt:
    store: str
    currency: Literal["INR", "USD", "EUR"]
    items: list[Item]
    total: float
    date: Optional[str] = None


def from_dict(cls: Any, data: Any) -> Any:
    """Build a dataclass from a dict, following its type hints. Raises TypeError with a path."""
    return _convert(cls, data, "$")


def _convert(tp: Any, data: Any, path: str) -> Any:
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if dataclasses.is_dataclass(tp):
        if not isinstance(data, dict):
            raise TypeError(f"{path}: expected object for {tp.__name__}")
        hints = typing.get_type_hints(tp)
        kwargs = {}
        for f in dataclasses.fields(tp):
            if f.name in data:
                kwargs[f.name] = _convert(hints[f.name], data[f.name], f"{path}.{f.name}")
            elif f.default is dataclasses.MISSING:
                raise TypeError(f"{path}.{f.name}: required")
        return tp(**kwargs)
    if origin is list:
        if not isinstance(data, list):
            raise TypeError(f"{path}: expected array")
        return [_convert(args[0], x, f"{path}[{i}]") for i, x in enumerate(data)]
    if origin is Literal:
        if data not in args:
            raise TypeError(f"{path}: must be one of {list(args)}, got {data!r}")
        return data
    if origin is typing.Union:                                     # Optional[X]
        if data is None and type(None) in args:
            return None
        return _convert(next(a for a in args if a is not type(None)), data, path)
    if tp is float and is_type(data, "number"):
        return float(data)
    if tp is int and is_type(data, "integer"):
        return data
    if tp is str and isinstance(data, str):
        return data
    raise TypeError(f"{path}: expected {getattr(tp, '__name__', tp)}, got {json_type(data)}")

# ---------------------------------------------------------------- layer 3: meaning


def check_rules(r: Receipt) -> list[str]:
    errors = []
    computed = round(sum(i.qty * i.unit_price for i in r.items), 2)
    if abs(computed - r.total) > 0.01:
        errors.append(f"$.total: {r.total} does not equal the sum of qty x unit_price = {computed}")
    for n, item in enumerate(r.items):
        if item.qty < 1:
            errors.append(f"$.items[{n}].qty: must be at least 1")
    return errors

# ---------------------------------------------------------------- the schema the model sees

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["store", "currency", "items", "total"],
    "properties": {
        "store": {"type": "string", "minLength": 1},
        "currency": {"type": "string", "enum": ["INR", "USD", "EUR"]},
        "date": {"type": ["string", "null"], "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
        "total": {"type": "number", "minimum": 0},
        "items": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "qty", "unit_price"],
            "properties": {"name": {"type": "string", "minLength": 1}, "qty": {"type": "integer", "minimum": 1},
                           "unit_price": {"type": "number", "minimum": 0}}}},
    },
}

# ---------------------------------------------------------------- parse with repair


@dataclass
class Outcome:
    receipt: Receipt | None
    attempts: int
    errors: list[list[str]]          # the errors after each attempt


LLM = Callable[[list[dict]], str]
SYSTEM = ("Extract the receipt as JSON matching this schema. Reply with JSON only.\n" + json.dumps(SCHEMA)
          + "\nunit_price is the price of ONE unit. total is the amount actually paid.")


def parse_receipt(text: str, llm: LLM, max_attempts: int = 3) -> Outcome:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]
    history: list[list[str]] = []
    for attempt in range(1, max_attempts + 1):
        reply = llm(messages)
        try:
            data = json.loads(reply)
            errors = validate(data, SCHEMA)
            receipt = from_dict(Receipt, data) if not errors else None
            if receipt:
                errors = check_rules(receipt)
        except (json.JSONDecodeError, TypeError) as exc:
            errors, receipt = [f"$: {exc}"], None
        history.append(errors)
        if not errors:
            return Outcome(receipt, attempt, history)
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": "Your JSON has these problems:\n- " + "\n- ".join(errors)
                      + "\nRe-read the receipt and reply with corrected JSON only."}]
    return Outcome(None, max_attempts, history)

# ---------------------------------------------------------------- data and models

RECEIPTS = [
    ("CHAI POINT, Koramangala  2026-11-02\n2 x Masala chai @ 40.00\n1 x Samosa @ 25.00\nTOTAL INR 105.00",
     {"store": "CHAI POINT", "currency": "INR", "total": 105.0, "items": 2}),
    ("Blue Bottle Coffee\nNov 3 2026\nLatte  1  $5.50\nCroissant  2  $3.75\nTotal: $13.00",
     {"store": "Blue Bottle Coffee", "currency": "USD", "total": 13.0, "items": 2}),
    ("Bäckerei Müller - 03.11.2026\n3 Brezel je 1,20 EUR\n1 Kaffee 2,80 EUR\nSumme 6,40 EUR",
     {"store": "Bäckerei Müller", "currency": "EUR", "total": 6.4, "items": 2}),
    ("Hardware Hub\n12 screws (0.15 each)\n1 hammer 349.00\n2 tape rolls @ 60\nGrand total Rs. 470.80",
     {"store": "Hardware Hub", "currency": "INR", "total": 470.8, "items": 3}),
    ("Corner Deli 11/04/2026\nSandwich 7.25\nSoda 2 @ 1.50\nTOTAL USD 10.25",
     {"store": "Corner Deli", "currency": "USD", "total": 10.25, "items": 2}),
]


def correct(r: Receipt | None, gold: dict) -> bool:
    return bool(r) and r.currency == gold["currency"] and abs(r.total - gold["total"]) < 0.01 \
        and len(r.items) == gold["items"] and gold["store"].lower() in r.store.lower()


def scripted(replies: list[str]) -> LLM:
    it = iter(replies)
    return lambda messages: next(it)


def ollama_json(model: str, base: str, temperature: float = 0.7) -> LLM:
    def call(messages: list[dict]) -> str:
        body = {"model": model, "messages": messages, "stream": False, "format": "json",
                "options": {"temperature": temperature}}
        req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["message"]["content"]
    return call


DEMO = [
    '{"store": "Blue Bottle Coffee", "currency": "$", "items": [{"name": "Latte", "qty": 1, "unit_price": 5.5},'
    ' {"name": "Croissant", "qty": "2", "unit_price": 3.75}], "total": 13.0}',
    '{"store": "Blue Bottle Coffee", "currency": "USD", "items": [{"name": "Latte", "qty": 1, "unit_price": 5.5},'
    ' {"name": "Croissant", "qty": 2, "unit_price": 7.5}], "total": 13.0}',
    '{"store": "Blue Bottle Coffee", "currency": "USD", "date": "2026-11-03", "items": [{"name": "Latte", "qty": 1,'
    ' "unit_price": 5.5}, {"name": "Croissant", "qty": 2, "unit_price": 3.75}], "total": 13.0}',
]


def live(runs: int) -> None:
    llm = ollama_json(os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    first = after = right = attempts = 0
    kinds: dict[str, int] = {}
    n = len(RECEIPTS) * runs
    for text, gold in RECEIPTS:
        for _ in range(runs):
            o = parse_receipt(text, llm)
            first += not o.errors[0]
            after += o.receipt is not None
            right += correct(o.receipt, gold)
            attempts += o.attempts
            for e in o.errors[0]:
                kinds[e] = kinds.get(e, 0) + 1
            if o.receipt and not correct(o.receipt, gold):
                print(f"  valid but wrong: {o.receipt}")
    print(f"valid on first try: {first}/{n}   valid within 3 attempts: {after}/{n}   "
          f"correct vs gold: {right}/{n}   avg attempts {attempts / n:.2f}")
    print("first-attempt errors:")
    for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {v:3}  {k}")


if __name__ == "__main__":
    if "--live" in sys.argv:
        i = sys.argv.index("--live")
        live(int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 3)
        sys.exit()
    o = parse_receipt(RECEIPTS[1][0], scripted(DEMO))
    for n, errs in enumerate(o.errors, 1):
        print(f"attempt {n}: {errs or 'valid'}")
    print("\nresult:", o.receipt)
