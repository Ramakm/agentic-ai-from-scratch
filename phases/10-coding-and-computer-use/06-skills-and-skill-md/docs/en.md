# Skills and SKILL.md

> A skill is a folder with a `SKILL.md`: a name, a description that says when to use it, and instructions. The agent sees every skill's description all the time, loads one skill's instructions only when a task matches, and reads the skill's extra files only when the instructions point to them. That's progressive disclosure, and it lets an agent carry fifty skills for the cost of fifty sentences.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 10 · Repository maps & context; Phase 4 · Context is the program; Phase 7 · Tools, resources & prompts
**Time:** ~45 minutes

## Learning Objectives

- Parse and validate `SKILL.md` frontmatter: name format, folder match, description length, and "when to use it".
- Implement three levels of loading: catalog in the system prompt, body on demand, bundled files on demand.
- Measure the token difference between progressive loading and loading everything.
- Write descriptions that make the right skill get picked.

## The Problem

Your team's agent needs to know how to write release notes, how to triage a production alert, how your PDF reports are styled, and how to debug a stuck agent. You paste all of it into the system prompt. It's 20,000 tokens, every request pays for it, and the model mixes up the release-note rules with the alert runbook.

You need the knowledge *available* without it being *present*. And whoever maintains each piece of know-how should be able to change it without editing one giant prompt.

## The Concept

| Level | What the model sees | When | Cost |
|-------|---------------------|------|------|
| 1. Catalog | `- name: description` for every skill | Always, in the system prompt | ~one sentence per skill |
| 2. Instructions | The `SKILL.md` body | After the agent calls `load_skill(name)` | Only for matching tasks |
| 3. Resources | Bundled files: templates, style guides, scripts, references | When the instructions say to read one | Only the file needed |

A skill folder:

| File | Purpose |
|------|---------|
| `SKILL.md` | Frontmatter (`name`, `description`) + instructions |
| `STYLE.md`, `reference/*.md` | Extra knowledge, read only when needed |
| `scripts/*.py` | Code the agent can run instead of re-deriving it |

**The description is the trigger.** At level 1 it's all the model has to decide with. A description must say *what* the skill does and *when* to use it. "Helps with documents." matches everything and nothing.

## Build It

```bash
cd code
python3 main.py
```

The demo discovers this course's own `skills/` folder, the skills you install with `npx skills add`.

### Step 1: parse the frontmatter

```python
meta, body = parse_frontmatter(text)
# description: >        <- folded: lines joined with spaces
#   Diagnose a misbehaving AI agent ...
```

`SKILL.md` frontmatter is YAML. We parse the subset skills use (`key: value`, folded `>` and literal `|` blocks) rather than pull in a YAML library.

### Step 2: validate

```python
if not NAME_RE.match(name) or len(name) > 64: ...      # lowercase letters, digits, hyphens
elif name != folder.name: ...                          # the folder is the skill's identity
if len(desc) > 1024: ...
elif not re.search(r"\b(use when|use it when|trigger|when (?:the|a|someone|you))", desc, re.I):
    problems.append("description doesn't say WHEN to use the skill ...")
```

Hard errors (missing or malformed name, missing description) reject the skill. A description with no "when" still loads, with a warning.

### Step 3: three levels

```python
def catalog(self):                        # level 1
    return "\n".join(f"- {s.name}: {s.description}" for s in self.skills.values())

def load_skill(self, name):               # level 2
    return s.body + "Bundled files you can read with read_skill_file: ..."

def read_skill_file(self, name, path):    # level 3, jailed to the skill's folder
```

### Step 4: run it

```text
discovered 5 skills in skills/
  level 1 (names + descriptions, always in context): ~517 tokens
  all bodies loaded up front instead:                ~4352 tokens

task: My agent keeps calling the same tool forever and never answers. Help?
loaded skills: ['debug-my-agent'] (+~762 tokens)
answer: Following the debug-my-agent skill: paste your agent's trace and I'll start with the stop condition, since a loop that never ends usually lacks one.

validating sample skills:
  loaded: ['pdf-report', 'vague']
  Bad_Name: name 'Bad_Name' must be lowercase letters, digits and hyphens, at most 64 characters; description doesn't say WHEN to use the skill (add 'Use when …' or trigger phrases)
  vague: description doesn't say WHEN to use the skill (add 'Use when …' or trigger phrases)
  level 3: pdf-report bundles ['STYLE.md']; read on demand -> 'Fonts: Inter 11pt. Colours: #1f2937 text, #2563eb accents.'
```

The task cost ~517 + 762 tokens of skill context instead of ~4,352. With 50 skills the gap is much larger. All five of the course's skills passed validation: their descriptions end with trigger phrases.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Where | How skills are found and loaded |
|-------|---------------------------------|
| Claude Code | Personal skills in `~/.claude/skills/`, project skills in `.claude/skills/`, and skills from plugins; descriptions are shown to the model, bodies load when used |
| Claude apps and API | Upload skills; the model loads them when a task matches |
| Claude Agent SDK | Loads skills from the same filesystem locations as Claude Code |
| Other agents | The format is published as an open standard (Agent Skills), and tools like `npx skills add` install skills for several agents |
| This course | `npx skills add Ramakm/agentic-ai-from-scratch` installs the five tutor skills; every lesson's `outputs/skill-*.md` follows the same frontmatter |

Skills and MCP complement each other: an MCP server gives an agent new *capabilities* (tools to call), while a skill gives it *know-how* (how to do a task, possibly using those tools).

## Ship It

`outputs/skill-skill-author.md` is a skill for writing skills: pick a name that matches the folder, write a description with what + when, keep the body to the steps, and move long references into bundled files the body points to.

## Exercises

1. **Easy.** Add `outputs/skill-*.md` files from three lessons to a temp `skills/` folder (one folder each, renamed to `SKILL.md`). Do they pass validation?
2. **Medium.** Two skills with overlapping descriptions: "Write release notes" and "Write a changelog". Give a real model 10 tasks and count wrong picks. Rewrite the descriptions until it picks correctly.
3. **Medium.** Add a `scripts/` resource: a skill that includes `count_words.py`, and a `run_skill_script` tool that runs it in the Lesson 3 sandbox.
4. **Hard.** Add a budget: if the catalog exceeds N tokens, include only the top-k skills by embedding similarity to the task (Phase 4) and note how many were hidden.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Skill | "Agent plugin" | A folder of instructions and resources the agent loads when relevant |
| SKILL.md | "Skill file" | The skill's entry point: YAML frontmatter plus Markdown instructions |
| Progressive disclosure | "Lazy loading" | Showing descriptions always, instructions on demand, resources only when needed |
| Description | "Trigger" | The one or two sentences the model uses to decide whether to load the skill |
| Bundled resource | "Skill files" | Extra files in the skill folder, read only when the instructions need them |

## Further Reading

- [Anthropic, Equipping agents for the real world with Agent Skills (2025)](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Claude docs: Agent Skills overview](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview)
- [Claude Code: skills](https://docs.claude.com/en/docs/claude-code/skills)
- [Agent Skills open specification](https://agentskills.io/)
- [Anthropic skills repository](https://github.com/anthropics/skills)
