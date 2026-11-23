"""Tool results that fit the context: the same search, shaped five ways. Measure tokens and answers.

  raw       every match, every field, pretty-printed JSON
  fields    only the fields the agent asked for
  page      fields + a page of 10, a total count and a cursor
  table     the page as a compact text table
  filtered  the tool does the filtering and sorting the question needs (in_stock, max_price, sort)
  top       filtered, then only the count and the first row: exactly what the question needs

    python3 main.py             # offline: sizes of each shape (characters / 4 as a rough token estimate)
    python3 main.py --live      # live: real prompt tokens and llama3.2's answer for 4 questions x 6 shapes
"""
from __future__ import annotations

import json
import os
import random
import sys
import urllib.request
from typing import Any

# ---------------------------------------------------------------- a catalogue with realistic bulk

CATEGORIES = ["kettle", "mug", "teapot", "pan", "knife"]


def make_catalogue(n: int = 200, seed: int = 4) -> list[dict]:
    rng = random.Random(seed)
    items = []
    for i in range(n):
        cat = CATEGORIES[i % len(CATEGORIES)]
        items.append({
            "id": f"P-{1000 + i}", "name": f"{rng.choice(['Nordic', 'Classic', 'Studio', 'Copper', 'Everyday'])} {cat} {i}",
            "category": cat, "price": round(rng.uniform(150, 4000), 2), "currency": "INR",
            "in_stock": rng.random() > 0.35, "rating": round(rng.uniform(2.5, 5.0), 1),
            "description": f"A {cat} made for daily use. " + "Durable, easy to clean, and backed by a two-year warranty. " * 3,
            "specs": {"weight_g": rng.randint(150, 2500), "material": rng.choice(["steel", "ceramic", "copper", "glass"])},
            "reviews": [{"stars": rng.randint(1, 5), "text": "Works as described, would buy again."} for _ in range(3)],
        })
    return items


CATALOGUE = make_catalogue()

# ---------------------------------------------------------------- the search tool and its shapes


def search(category: str, fields: list[str] | None = None, limit: int | None = None, cursor: int = 0,
           in_stock: bool | None = None, max_price: float | None = None, sort: str = "") -> dict:
    rows = [p for p in CATALOGUE if p["category"] == category]
    if in_stock is not None:
        rows = [p for p in rows if p["in_stock"] == in_stock]
    if max_price is not None:
        rows = [p for p in rows if p["price"] <= max_price]
    if sort in ("price", "-price", "rating", "-rating"):
        rows = sorted(rows, key=lambda p: p[sort.lstrip("-")], reverse=sort.startswith("-"))
    total = len(rows)
    if limit is not None:
        rows = rows[cursor:cursor + limit]
    if fields:
        rows = [{k: p[k] for k in fields if k in p} for p in rows]
    out: dict[str, Any] = {"total": total, "results": rows}
    if limit is not None:
        out["next_cursor"] = cursor + limit if cursor + limit < total else None
    return out


def as_table(result: dict) -> str:
    rows = result["results"]
    if not rows:
        return f"total {result['total']}: no rows"
    cols = list(rows[0])
    lines = [" | ".join(cols)] + [" | ".join(str(r[c]) for c in cols) for r in rows]
    more = f"; next_cursor {result['next_cursor']}" if result.get("next_cursor") is not None else ""
    return f"total {result['total']} (showing {len(rows)}{more})\n" + "\n".join(lines)


FIELDS = ["id", "name", "price", "in_stock"]


def shaped(shape: str, category: str, filters: dict) -> str:
    if shape == "raw":
        return json.dumps(search(category), indent=2)
    if shape == "fields":
        return json.dumps(search(category, fields=FIELDS))
    if shape == "page":
        return json.dumps(search(category, fields=FIELDS, limit=10))
    if shape == "table":
        return as_table(search(category, fields=FIELDS, limit=10))
    if shape == "filtered":
        return as_table(search(category, fields=FIELDS, limit=10, **filters))
    if shape == "top":
        r = search(category, fields=FIELDS, limit=1, **filters)
        first = r["results"][0] if r["results"] else None
        return json.dumps({"matching": r["total"], "filters": filters or "none", "first_after_sort": first})
    raise ValueError(shape)


SHAPES = ["raw", "fields", "page", "table", "filtered", "top"]

# ---------------------------------------------------------------- questions with ground truth


def truth_cheapest_in_stock(cat: str) -> dict:
    return min((p for p in CATALOGUE if p["category"] == cat and p["in_stock"]), key=lambda p: p["price"])


QUESTIONS = [
    ("Which in-stock kettle is the cheapest? Give its id.", "kettle", {"in_stock": True, "sort": "price"},
     lambda a: truth_cheapest_in_stock("kettle")["id"] in a),
    ("How many mugs are there in total?", "mug", {},
     lambda a: str(sum(p["category"] == "mug" for p in CATALOGUE)) in a),
    ("How many teapots cost under 1000 rupees? Give the number.", "teapot", {"max_price": 1000},
     lambda a: str(sum(p["category"] == "teapot" and p["price"] < 1000 for p in CATALOGUE)) in a.replace(",", "")),
    ("What is the price of the most expensive pan? Give the number.", "pan", {"sort": "-price"},
     lambda a: str(max(p["price"] for p in CATALOGUE if p["category"] == "pan")) in a.replace(",", "")),
]

# ---------------------------------------------------------------- live


def ask(question: str, category: str, result: str) -> tuple[str, int]:
    base, model = os.environ.get("OLLAMA_URL", "http://localhost:11434"), os.environ.get("AGENT_MODEL", "llama3.2")
    messages = [{"role": "user", "content": question},
                {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_products",
                                                                                  "arguments": {"category": category}}}]},
                {"role": "tool", "content": result}]
    tool = [{"type": "function", "function": {"name": "search_products", "description": "Search products by category.",
             "parameters": {"type": "object", "properties": {"category": {"type": "string"}}, "required": ["category"]}}}]
    body = {"model": model, "stream": False, "messages": messages, "tools": tool,
            "options": {"temperature": 0, "num_ctx": 16384, "num_predict": 120}}
    req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=300))
    return r["message"].get("content") or "", r["prompt_eval_count"]


def live() -> None:
    score = {s: 0 for s in SHAPES}
    tokens = {s: [] for s in SHAPES}
    for q, cat, filters, check in QUESTIONS:
        print(q)
        for s in SHAPES:
            answer, n = ask(q, cat, shaped(s, cat, filters))
            ok = check(answer)
            score[s] += ok
            tokens[s].append(n)
            print(f"  {s:9} {n:6} tokens  {'PASS' if ok else 'fail'}  {answer.strip()[:70]!r}")
    print("\n" + "\n".join(f"{s:9} correct {score[s]}/{len(QUESTIONS)}   mean prompt tokens {sum(tokens[s]) // len(tokens[s]):6}"
                           for s in SHAPES))


if __name__ == "__main__":
    if "--live" in sys.argv:
        live()
        sys.exit()
    q, cat, filters, _ = QUESTIONS[0]
    print(f"'{q}'  ({sum(p['category'] == cat for p in CATALOGUE)} kettles in the catalogue)\n")
    for s in SHAPES:
        text = shaped(s, cat, filters)
        print(f"{s:9} {len(text):7,} chars  ~{len(text) // 4:6,} tokens (estimate)")
    print("\nfiltered result:\n" + shaped("filtered", cat, filters))
