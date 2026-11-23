"""Repository maps: give a coding agent the shape of a codebase in a few hundred tokens.
Parse every file, extract definitions and references, rank files with PageRank biased
toward the task, and print signatures (not bodies) until the token budget runs out.

    python3 main.py                                  # map a built-in demo repo for a task
    python3 main.py --repo path/to/python/project --task "fix login timeout" --budget 800

Standard library only.
"""
from __future__ import annotations

import argparse
import ast
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist"}


@dataclass
class FileInfo:
    path: str
    defines: dict[str, str] = field(default_factory=dict)     # symbol -> signature line
    references: set[str] = field(default_factory=set)
    chars: int = 0


def signature(node: ast.AST, prefix: str = "") -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = ast.unparse(node.args)
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix}{kw} {node.name}({args}){ret}"
    if isinstance(node, ast.ClassDef):
        bases = f"({', '.join(ast.unparse(b) for b in node.bases)})" if node.bases else ""
        return f"{prefix}class {node.name}{bases}"
    return ""


def parse_file(path: Path, rel: str) -> FileInfo | None:
    text = path.read_text(errors="ignore")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    info = FileInfo(rel, chars=len(text))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            info.defines[node.name] = signature(node)
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("__"):
                        info.defines[f"{node.name}.{item.name}"] = signature(item, "    ")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            info.references.add(node.id)
        elif isinstance(node, ast.Attribute):
            info.references.add(node.attr)
    return info


def scan(root: Path) -> dict[str, FileInfo]:
    files = {}
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if SKIP & set(rel.parts):
            continue
        info = parse_file(p, str(rel))
        if info:
            files[str(rel)] = info
    return files


def words(text: str) -> set[str]:
    """Split identifiers and prose the same way: apply_discount -> apply, discount; CartTotal -> cart, total."""
    out = set()
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        for part in re.split(r"_|(?<=[a-z])(?=[A-Z])", token):
            if len(part) > 2:
                out.add(part.lower())
    return out


def rank(files: dict[str, FileInfo], task: str, damping: float = 0.85, iters: int = 40) -> dict[str, float]:
    """PageRank over 'file A uses a name file B defines', personalised toward files that match the task."""
    definers = defaultdict(set)
    for f, info in files.items():
        for sym in info.defines:
            definers[sym.split(".")[-1]].add(f)
    edges = defaultdict(lambda: defaultdict(float))
    for f, info in files.items():
        for ref in info.references:
            for target in definers.get(ref, ()):
                if target != f:
                    edges[f][target] += 1.0
    task_words = words(task)
    bias = {}
    for f, info in files.items():
        hits = len(task_words & (words(f) | {w for s in info.defines for w in words(s)}))
        bias[f] = 1.0 + 10.0 * hits
    total = sum(bias.values())
    bias = {f: b / total for f, b in bias.items()}
    score = dict(bias)
    for _ in range(iters):
        nxt = {f: (1 - damping) * bias[f] for f in files}
        for f in files:
            out = edges.get(f)
            if out:
                weight = sum(out.values())
                for target, w in out.items():
                    nxt[target] += damping * score[f] * w / weight
            else:                                   # dangling file: spread its score by the bias
                for g in files:
                    nxt[g] += damping * score[f] * bias[g]
        score = nxt
    return score


def render(files: dict[str, FileInfo], scores: dict[str, float], budget_tokens: int) -> tuple[str, list[str]]:
    """Signatures of the best-ranked files, stopping before the budget (≈4 characters per token)."""
    lines, included = [], []
    for f in sorted(files, key=lambda f: -scores[f]):
        block = [f"{f}:"] + [f"  {sig}" for sig in files[f].defines.values()] or [f"{f}: (no definitions)"]
        if sum(len(x) + 1 for x in lines + block) / 4 > budget_tokens:
            continue                                # skip files that don't fit; smaller ones still might
        lines += block
        included.append(f)
    return "\n".join(lines), included

# ---------------------------------------------------------------- demo repo

DEMO = {
    "shop/models.py": "class Item:\n    def __init__(self, sku: str, price: float, qty: int): ...\n\n"
                      "class Cart:\n    def add(self, item: Item) -> None: ...\n    def items(self) -> list[Item]: ...\n",
    "shop/pricing.py": "from shop.models import Cart\n\n\ndef subtotal(cart: Cart) -> float:\n    return sum(i.price * i.qty "
                       "for i in cart.items())\n\n\ndef apply_discount(amount: float, code: str) -> float:\n"
                       "    return amount * 0.9 if code == 'SAVE10' else amount\n",
    "shop/checkout.py": "from shop.pricing import subtotal, apply_discount\nfrom shop.tax import add_tax\n\n\n"
                        "def checkout_total(cart, code: str = '') -> float:\n"
                        "    return add_tax(apply_discount(subtotal(cart), code))\n",
    "shop/tax.py": "def add_tax(amount: float, rate: float = 0.08) -> float:\n    return round(amount * (1 + rate), 2)\n",
    "shop/api.py": "from shop.checkout import checkout_total\nfrom shop.auth import require_user\n\n\n"
                   "def post_checkout(request) -> dict:\n    require_user(request)\n"
                   "    return {'total': checkout_total(request.cart, request.code)}\n",
    "shop/auth.py": "def require_user(request) -> str:\n    ...\n\n\ndef login(username: str, password: str) -> str:\n    ...\n",
    "shop/emails.py": "def send_receipt(email: str, total: float) -> None:\n    ...\n\n\n"
                      "def render_template(name: str, **ctx) -> str:\n    ...\n",
    "shop/admin/reports.py": "from shop.pricing import subtotal\n\n\nclass SalesReport:\n"
                             "    def daily(self, day: str) -> dict: ...\n    def export_csv(self, path: str) -> None: ...\n",
    "shop/legacy/broken.py": "def oops(:\n",
}


def make_demo_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="repomap-"))
    for rel, text in DEMO.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path)
    ap.add_argument("--task", default="The discount code is applied after tax in checkout totals. Fix it.")
    ap.add_argument("--budget", type=int, default=120, help="token budget for the map")
    args = ap.parse_args()
    root = args.repo or make_demo_repo()
    files = scan(root)
    scores = rank(files, args.task)
    repo_map, included = render(files, scores, args.budget)
    total_chars = sum(f.chars for f in files.values())
    print(f"task: {args.task}\n")
    print("ranking:")
    for f in sorted(files, key=lambda f: -scores[f]):
        print(f"  {scores[f]:.3f}  {f}{'' if f in included else '   (left out: budget)'}")
    print(f"\nrepo map ({len(repo_map) // 4} tokens of {args.budget} budget; whole repo is ~{total_chars // 4} tokens):\n")
    print(repo_map)
    if not args.repo:
        other = "Users get logged out when they log in with a long password."
        top = sorted(files, key=lambda f: -rank(files, other)[f])[:3]
        print(f"\nsame repo, different task: {other!r}\n  top 3: {', '.join(top)}")
        print(f"files skipped because they don't parse: {sorted(set(DEMO) - set(files))}")
