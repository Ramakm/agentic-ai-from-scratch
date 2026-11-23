"""Structured output: three ways to get JSON out of a model, and how often each one works.

  1. prompt only   - ask for JSON in the instructions
  2. JSON mode     - the server guarantees syntactically valid JSON (any shape)
  3. schema mode   - the server constrains generation to your JSON Schema

    python3 main.py             # offline: what each failure looks like, and the extractor/validator
    python3 main.py --live 3    # live: 6 emails x 3 runs x 3 modes against Ollama, scored
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from typing import Any, Callable

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        # [0-9], not \d: with \d, Ollama 0.15.1's schema mode crashed its model runner (HTTP 500)
        "order_id": {"type": ["string", "null"], "pattern": "^A-[0-9]{4}$"},
        "issue": {"type": "string", "enum": ["damaged", "late", "wrong_item", "other"]},
        "wants_refund": {"type": "boolean"},
    },
    "required": ["name", "order_id", "issue", "wants_refund"],
    "additionalProperties": False,
}

INSTRUCTIONS = ("Extract these fields from the customer email and reply with JSON only:\n"
                "- name: the customer's name\n"
                "- order_id: like A-1234, or null if none is given\n"
                "- issue: one of damaged, late, wrong_item, other\n"
                "- wants_refund: true or false")

# ---------------------------------------------------------------- getting JSON out of text


def extract_json(text: str) -> Any:
    """Strict first; then strip a code fence; then take the first {...} object in the text."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    if start >= 0:
        try:
            return json.JSONDecoder().raw_decode(text[start:])[0]
        except json.JSONDecodeError:
            pass
    raise ValueError("no JSON object found")


TYPES = {"string": str, "boolean": bool, "object": dict, "array": list, "null": type(None)}


def validate(value: Any, schema: dict) -> list[str]:
    """A small JSON Schema subset: object, required, additionalProperties, type (incl. lists), enum, pattern."""
    if not isinstance(value, dict):
        return [f"expected an object, got {type(value).__name__}"]
    errors = [f"missing {k!r}" for k in schema["required"] if k not in value]
    for k, v in value.items():
        spec = schema["properties"].get(k)
        if spec is None:
            if schema.get("additionalProperties") is False:
                errors.append(f"unexpected {k!r}")
            continue
        kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        if not any(isinstance(v, TYPES[t]) and not (t != "boolean" and isinstance(v, bool)) for t in kinds):
            errors.append(f"{k!r} should be {' or '.join(kinds)}, got {type(v).__name__}")
            continue
        if "enum" in spec and v not in spec["enum"]:
            errors.append(f"{k!r} must be one of {spec['enum']}, got {v!r}")
        if "pattern" in spec and isinstance(v, str) and not re.search(spec["pattern"], v):
            errors.append(f"{k!r} must match {spec['pattern']}, got {v!r}")
    return errors

# ---------------------------------------------------------------- the data

EMAILS = [
    ("Hi, I'm Priya Shah. Order A-1001 arrived today and the teapot is cracked. I'd like my money back please.",
     {"name": "Priya Shah", "order_id": "A-1001", "issue": "damaged", "wants_refund": True}),
    ("Hello, this is Tom. My kettle (order A-2044) was supposed to arrive last Friday. Still nothing. Just tell me when it's coming.",
     {"name": "Tom", "order_id": "A-2044", "issue": "late", "wants_refund": False}),
    ("You sent me a frying pan but I ordered a wok!! Order number A-3310. Please swap it. - Mei Lin",
     {"name": "Mei Lin", "order_id": "A-3310", "issue": "wrong_item", "wants_refund": False}),
    ("Dear Acme, the knife set I bought has a broken handle. I don't have my order number. Refund please. Regards, Arjun Rao",
     {"name": "Arjun Rao", "order_id": None, "issue": "damaged", "wants_refund": True}),
    ("Hi! Do you sell cast-iron pans in a 30 cm size? Thanks, Sofia",
     {"name": "Sofia", "order_id": None, "issue": "other", "wants_refund": False}),
    ("Order A-0420 for Daniel Kim is two weeks late. Cancel it and refund me.",
     {"name": "Daniel Kim", "order_id": "A-0420", "issue": "late", "wants_refund": True}),
]


def score(reply: str, gold: dict) -> dict[str, Any]:
    """parsed? schema-valid? how many of the 4 fields equal the gold answer?"""
    try:
        value = extract_json(reply)
    except ValueError:
        return {"parsed": False, "valid": False, "fields": 0, "strict": False}
    strict = True
    try:
        json.loads(reply)
    except json.JSONDecodeError:
        strict = False
    errors = validate(value, SCHEMA)
    fields = sum(isinstance(value, dict) and value.get(k) == v for k, v in gold.items())
    return {"parsed": True, "valid": not errors, "fields": fields, "strict": strict}

# ---------------------------------------------------------------- models

Call = Callable[[str], str]


def ollama(mode: str, model: str, base: str) -> Call:
    """mode: 'prompt' (no format), 'json' (format: "json"), 'schema' (format: the JSON Schema)."""
    def call(email: str) -> str:
        body: dict[str, Any] = {"model": model, "stream": False, "options": {"temperature": 0.7},
                                "messages": [{"role": "system", "content": INSTRUCTIONS},
                                             {"role": "user", "content": email}]}
        if mode == "json":
            body["format"] = "json"
        elif mode == "schema":
            body["format"] = SCHEMA
        req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["message"]["content"]
    return call


def live(runs: int) -> None:
    base = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    model = os.environ.get("AGENT_MODEL", "llama3.2")
    n = len(EMAILS) * runs
    print(f"{'mode':8} {'strict JSON':>11} {'extractable':>11} {'schema-valid':>12} {'fields right':>12}")
    for mode in ("prompt", "json", "schema"):
        call = ollama(mode, model, base)
        totals = {"parsed": 0, "valid": 0, "fields": 0, "strict": 0}
        misses: list[str] = []
        for email, gold in EMAILS:
            for _ in range(runs):
                reply = call(email)
                s = score(reply, gold)
                for k in totals:
                    totals[k] += s[k]
                if s["fields"] < 4 and len(misses) < 2:
                    misses.append(reply.strip().replace("\n", " ")[:110])
        print(f"{mode:8} {totals['strict']:>8}/{n} {totals['parsed']:>8}/{n} {totals['valid']:>9}/{n} "
              f"{totals['fields']:>8}/{n * 4}")
        for m in misses:
            print(f"         e.g. {m!r}")


SAMPLES = {
    "clean": '{"name": "Tom", "order_id": "A-2044", "issue": "late", "wants_refund": false}',
    "chatty": 'Here is the JSON:\n```json\n{"name": "Tom", "order_id": "A-2044", "issue": "late", "wants_refund": false}\n```',
    "wrong enum": '{"name": "Tom", "order_id": "A-2044", "issue": "delayed", "wants_refund": "no"}',
    "bad id": '{"name": "Tom", "order_id": "2044", "issue": "late", "wants_refund": false, "mood": "annoyed"}',
    "truncated": '{"name": "Tom", "order_id": "A-2044", "iss',
}

if __name__ == "__main__":
    if "--live" in sys.argv:
        i = sys.argv.index("--live")
        live(int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 3)
        sys.exit()
    gold = EMAILS[1][1]
    for label, reply in SAMPLES.items():
        s = score(reply, gold)
        try:
            errs = validate(extract_json(reply), SCHEMA)
        except ValueError as exc:
            errs = [str(exc)]
        print(f"{label:11} strict={s['strict']!s:5} parsed={s['parsed']!s:5} valid={s['valid']!s:5} "
              f"fields={s['fields']}/4  {errs}")
