# Repository Maps & Context

> A coding agent can't read the whole repo, and it can't search for what it doesn't know exists. A repository map fixes both: signatures, not bodies, of the files that matter most for this task, in a few hundred tokens. Build it by parsing the code, linking "uses" to "defines", ranking with PageRank biased toward the task's words, and stopping at a token budget.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 10 · File read, edit & search tools; Phase 4 · Context is the program; Phase 5 · Graph-based retrieval
**Time:** ~50 minutes

## Learning Objectives

- Extract definitions (with signatures) and references from Python files with `ast`.
- Build a "uses → defines" graph and rank files with personalised PageRank.
- Render a map that fits a token budget, with the most relevant files first.
- Explain where word-overlap personalisation fails, and what real tools do instead.

## The Problem

"Fix the discount being applied after tax." The agent searches for `discount`, finds `apply_discount` in `pricing.py`, edits it, and the bug remains. The bug is in the *order of calls* in `checkout.py`, which never mentions the word "discount" in a way the agent searched for. Or the agent reads 40 files one by one to get oriented, using a third of its context before it writes a line.

What the agent lacks is a table of contents: what's defined where, what calls what, and which of that matters for this task. Humans build this in their heads over weeks. A repo map builds it in milliseconds.

## The Concept

| Step | What | Why |
|------|------|-----|
| Parse | `ast` per file: top-level functions, classes, methods → signatures; every `Name`/`Attribute` → references | Signatures say what's callable without the cost of bodies |
| Link | File A references a name that file B defines → edge A → B | Captures "what depends on what" |
| Personalise | Files whose path or definitions share words with the task get more starting weight | The same repo needs a different map for a different task |
| Rank | PageRank: score flows along edges toward heavily used definitions | Central code (models, utilities) and task-relevant code float up |
| Render | Highest-ranked files' signatures until the budget is spent | A predictable, bounded context cost |

**PageRank in one line:** each round, every file passes 85% of its score to the files it uses (split by how often it uses them), and 15% comes back from the task bias. After ~40 rounds, the scores settle.

## Build It

```bash
cd code
python3 main.py
python3 main.py --repo path/to/python/project --task "fix login timeout" --budget 800
```

### Step 1: signatures, not bodies

```python
def signature(node, prefix=""):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = ast.unparse(node.args)
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{prefix}def {node.name}({args}){ret}"
```

`ast.unparse` turns the parsed arguments back into source text, defaults and annotations included. Files that don't parse are skipped instead of crashing the map.

### Step 2: words from identifiers and prose

```python
words("apply_discount CartTotal to") == {"apply", "discount", "cart", "total"}
```

Splitting snake_case and CamelCase lets "discount" in the task match `apply_discount` in the code.

### Step 3: personalised PageRank

```python
bias[f] = 1.0 + 10.0 * hits          # hits = task words found in f's path or definitions
...
nxt[target] += damping * score[f] * w / weight
```

Files that define nothing used elsewhere and match nothing in the task end up near the bottom.

### Step 4: run it

```text
task: The discount code is applied after tax in checkout totals. Fix it.

ranking:
  0.227  shop/pricing.py
  0.204  shop/models.py
  0.179  shop/checkout.py
  0.176  shop/tax.py
  0.126  shop/api.py
  0.065  shop/auth.py   (left out: budget)
  0.011  shop/admin/reports.py   (left out: budget)
  0.011  shop/emails.py   (left out: budget)

repo map (103 tokens of 120 budget; whole repo is ~314 tokens):

shop/pricing.py:
  def subtotal(cart: Cart) -> float
  def apply_discount(amount: float, code: str) -> float
shop/models.py:
  class Item
  class Cart
      def add(self, item: Item) -> None
      def items(self) -> list[Item]
shop/checkout.py:
  def checkout_total(cart, code: str='') -> float
shop/tax.py:
  def add_tax(amount: float, rate: float=0.08) -> float
shop/api.py:
  def post_checkout(request) -> dict
```

With 103 tokens the agent sees that `checkout_total` combines `subtotal`, `apply_discount` and `add_tax`, which is exactly where the call order lives. Auth, emails and reports are left out.

### Step 5: a different task, and the method's limits

```text
same repo, different task: 'Users get logged out when they log in with a long password.'
  top 3: shop/models.py, shop/pricing.py, shop/auth.py
files skipped because they don't parse: ['shop/legacy/broken.py']
```

`auth.py` jumps from sixth to third, but `models.py` and `pricing.py` stay above it. Two reasons, both worth knowing:

1. **Structure dominates in small repos.** Everything uses `models.py`, so PageRank keeps it high whatever the task. That's often right: core types are context the agent needs.
2. **Word overlap is crude.** The task says "log in", the code says `login`. Only `password` (a parameter of `login`) matched. Stemming, synonyms, or embeddings (Phase 5) would do better, and so would raising the bias weight (Exercise 2).

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Tool | How it builds context |
|------|-----------------------|
| Aider | A repo map from tree-sitter parses across many languages, ranked with a graph algorithm and fitted to a token budget, sent with every request |
| Claude Code | No precomputed map: the agent explores with `Glob`/`Grep`/`Read`, guided by project instruction files (CLAUDE.md) |
| Cursor and other IDE agents | Embedding-based codebase indexes plus open files and symbols |
| SWE-agent | Search commands and a file viewer; the agent builds its own picture |
| LSP-backed tools | "Go to definition" and "find references" from a language server, exact rather than heuristic |

A precomputed map costs a fixed number of tokens on every turn and helps the first few steps most. Exploration costs nothing up front and more turns later. Many agents combine a short map or instruction file with search tools.

## Ship It

`outputs/skill-repo-context.md` is a skill for preparing a coding agent's context for a repository: write a short project instruction file (how to run tests, layout, conventions), generate a budgeted repo map for the task, and decide what to leave for the agent to search.

## Exercises

1. **Easy.** Run `main.py --repo` on a real Python project of yours with `--budget 500`. Is the top file the one you'd open first?
2. **Medium.** Change the bias from `1 + 10 * hits` to `1 + 50 * hits`. Where does `auth.py` land for the login task? What breaks?
3. **Medium.** Add stemming to `words()` (strip -ed, -ing, -s; join "log in" → "login"). Re-run the login task.
4. **Hard.** Replace word overlap with embeddings from Phase 4 · Embeddings from scratch: embed each file's signatures, embed the task, and use cosine similarity as the bias.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Repository map | "Repo map" | A budgeted list of files and their signatures, ranked for the task |
| Signature | "Function header" | Name, parameters, defaults and return type, without the body |
| Personalised PageRank | "Biased ranking" | PageRank where the restart probability favours task-relevant nodes |
| Token budget | "Context budget" | The maximum size the map may take in the prompt |
| Exploration | "Agentic search" | The agent finding context itself with search and read tools |

## Further Reading

- [Aider: repository map](https://aider.chat/docs/repomap.html)
- [Aider: building a better repository map with tree-sitter (2023)](https://aider.chat/2023/10/22/repomap.html)
- [Page, Brin et al., The PageRank citation ranking (1999)](http://ilpubs.stanford.edu:8090/422/)
- [Python docs: ast — abstract syntax trees](https://docs.python.org/3/library/ast.html)
- [Anthropic, Effective context engineering for AI agents (2025)](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
