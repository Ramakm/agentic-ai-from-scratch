# File Read, Edit & Search Tools

> A model can't see your editor. All it has is what your tools print. Good file tools page long files with line numbers, cap search results and say how many were hidden, edit by exact unique match, refuse edits to files the model hasn't read (or that changed since), and turn every failure into a message that tells the model what to do next.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 10 · Anatomy of a coding agent; Phase 2 · Designing tools models can use; Phase 2 · Tool results that fit the context
**Time:** ~55 minutes

## Learning Objectives

- Implement `read_file` with line numbers, paging, long-line truncation and binary detection.
- Implement a `search` that skips vendored directories, caps results and reports how many it hid.
- Implement exact-match `edit_file` with uniqueness checks, a read-before-edit guard, diffs and undo.
- Write failure messages that tell the model the next action, and recognise the short-`old` pitfall.

## The Problem

Give a model `open(path).read()` and `path.write_text(content)` and watch what happens. It reads a 4,000-line file into its context and forgets the top. It rewrites a whole file to change one line and drops a function it never saw. It edits `config.py` after another process changed it, and silently reverts that change. It searches for `get(` and drowns in 3,000 matches from `node_modules`.

None of these are model failures. They're tool design failures. The model can only be as careful as the tools let it be.

## The Concept

| Tool | Design choice | Why |
|------|---------------|-----|
| `read_file` | Line numbers, `offset` + `limit` (400 lines max), "N more lines, call with offset=…" | The model can cite lines and page instead of flooding its context |
| | Lines over 300 chars truncated; binary files refused | Minified JS and images waste thousands of tokens |
| `search` | Regex, glob filter, skip `.git`, `node_modules`, `__pycache__`… | Vendored code is noise |
| | Cap at 30 hits, then "… N more matches. Narrow the pattern" | The model learns its search was too broad |
| `edit_file` | Replace an exact string that must be unique (or `replace_all`) | Small, reviewable edits; no whole-file rewrites |
| | Refuse unless the file was read, and unchanged since | Prevents edits based on stale or imagined content |
| | Return a unified diff | The model and the human see exactly what changed |
| `create_file` | Refuse to overwrite unless asked | Prevents accidental clobbering |
| `undo_edit` | Keep previous versions per file | Cheap recovery from a bad edit |

**Failure messages are instructions.** Compare:

| Bad | Good |
|-----|------|
| `not found` | ``error: `old` was not found in shop/pricing.py. Line 1 matches if you ignore indentation: 'def calc_total(items):'. Copy whitespace exactly.`` |
| `ambiguous` | ``error: `old` appears 2 times in shop/cart.py (lines 1, 5). Include more surrounding lines to make it unique, or pass replace_all=true.`` |
| `no such file` | `error: shop/carts.py does not exist. Did you mean: shop/cart.py?` |

## Build It

```bash
cd code
python3 main.py
```

The demo replays a scripted session that renames `calc_total` to `order_total` across a small package, hitting every guard on the way.

### Step 1: paged reads

```python
chunk = lines[offset - 1: offset - 1 + limit]
out = [f"{i:>5}\t{line[:MAX_LINE]}{' …[line truncated]' if len(line) > MAX_LINE else ''}" for i, line in ...]
if end < len(lines):
    out.append(f"… {len(lines) - end} more lines. Call read_file with offset={end + 1} to continue.")
```

Reading also records a hash of the file, which `edit_file` checks.

### Step 2: the read-before-edit guard

```python
if path not in self.seen:
    return f"error: read {path} before editing it."
if self.seen[path] != _digest(text):
    return f"error: {path} changed since you last read it. Read it again before editing."
```

Claude Code's `Edit` tool enforces the same two rules. They stop the model editing from memory or from a stale view.

### Step 3: unique match, with hints

When `old` isn't found, `_hint` checks whether it matches with indentation ignored, then looks for the closest line with `difflib`. When it matches more than once, the error lists the line numbers.

### Step 4: run it

```text
> search(pattern='calc_total\\(')
  shop/cart.py:5: total = calc_total(cart)
  shop/pricing.py:1: def calc_total(items):
  shop/report.py:5: return [calc_total(o) for o in orders]

> edit_file(path='shop/cart.py', old='calc_total(cart)', new='order_total(cart)')
  error: read shop/cart.py before editing it.

> edit_file(path='shop/cart.py', old='calc_total', new='order_total')
  error: `old` appears 2 times in shop/cart.py (lines 1, 5). Include more surrounding lines to make it unique, or pass replace_all=true.

> edit_file(path='shop/cart.py', old='calc_total', new='order_total', replace_all=True)
  edited shop/cart.py (2 replacement(s))
  --- a/shop/cart.py
  +++ b/shop/cart.py
  @@ -1,2 +1,2 @@
  -from shop.pricing import calc_total
  +from shop.pricing import order_total
  ...

> edit_file(path='shop/pricing.py', old='def calc_total(items):\n  return', new='def order_total(items):\n    return')
  error: `old` was not found in shop/pricing.py. Line 1 matches if you ignore indentation: 'def calc_total(items):'. Copy whitespace exactly.

> search(pattern='calc_total')
  no matches for 'calc_total' in *
```

(Output trimmed; run it for the full session.) The final search confirms the rename, and `node_modules/lib/index.js`, which also says `calc_total`, was correctly skipped and left alone.

### Step 5: a pitfall we hit while writing the tests

Our first test used `old="  return sum"` (two spaces), expecting "not found". Instead the edit **succeeded**: two spaces plus `return sum` is a substring of the real line's four spaces plus `return sum`. The result was `  return 0(i['price'] …`, broken indentation and broken code. Exact matching doesn't protect against an `old` that's too short. Good habits, for models and the prompts you give them:

- Include whole lines in `old`, from the first character of the line.
- Include a line of context above or below when the text is common.
- Read the diff in the tool's response.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Agent | Read | Search | Edit |
|-------|------|--------|------|
| Claude Code | `Read` with line numbers, offset/limit | `Grep` (ripgrep), `Glob` | `Edit` exact unique replace, `replace_all`; must read first |
| SWE-agent | a windowed file viewer with scroll commands | `search_dir`, `search_file`, `find_file` | edit a line range, with a linter check |
| Aider | whole files added to the chat | repo map (Lesson 5) | search/replace blocks or unified diffs |
| OpenAI Codex CLI | shell commands | shell (`rg`) | `apply_patch` with a patch format |

Two broad edit styles exist: **exact replace** (this lesson, Claude Code) and **patch/diff** formats (Aider's diffs, Codex's `apply_patch`). Both need the same guards: target text must match exactly and uniquely, and failures must say why.

## Ship It

`outputs/skill-file-tool-design.md` is a checklist for designing or reviewing file tools for an agent: paging, caps with counts, skip lists, exact-and-unique edits, read-before-edit, diffs, undo, and failure messages that name the next action.

## Exercises

1. **Easy.** Add a `context` parameter to `search` that shows N lines around each hit.
2. **Medium.** Add a `view_range` edit mode: replace lines 10–14 with new text. What guard does it need that exact replace doesn't? (Hint: the line numbers must come from a fresh read.)
3. **Medium.** After every edit to a `.py` file, run `python -m py_compile` and append the result to the tool output. Make a syntax-breaking edit and see the message.
4. **Hard.** Implement `apply_patch` for unified diffs with fuzzy context matching. Compare its failure rate with exact replace on 20 edits from a real model.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Paging | "Read more" | Returning a slice of the file plus how to get the next slice |
| Exact replace | "str_replace" | Edit by replacing a literal string that must occur exactly once |
| Read-before-edit | "Stale edit protection" | Refusing to edit a file not read, or changed since it was read |
| Result cap | "Truncation" | Showing the first N results and saying how many were hidden |
| Skip list | "Ignore patterns" | Directories search never enters: VCS, dependencies, build output |
| Actionable error | "Helpful failure" | An error that tells the model what to do next |

## Further Reading

- [Anthropic, Text editor tool](https://docs.claude.com/en/docs/agents-and-tools/tool-use/text-editor-tool)
- [Yang et al., SWE-agent: Agent-computer interfaces (2024)](https://arxiv.org/abs/2405.15793), section on the file viewer and editor design
- [Aider: edit formats](https://aider.chat/docs/more/edit-formats.html)
- [ripgrep: how it decides what to search](https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md)
