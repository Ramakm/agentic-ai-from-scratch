# Role Design and Specialization

> A role is a contract: what this agent receives, what it must hand back, which tools it may use, and when it's done. Write roles as specs instead of personas, and you can lint a team for gaps and overlaps before running it, generate the prompts, and catch a role that breaks its contract at the handoff.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 8 · Lessons 2 and 3; Phase 1 · Lessons 5 and 7
**Time:** ~40 minutes

## Learning Objectives

- Write each role as a spec: goal, inputs, outputs with required fields, tools, side-effect permissions, done condition, revision limit.
- Lint a team for overlapping ownership, orphan outputs, missing inputs, vague goals, missing done conditions, excess privileges and unbounded loops.
- Generate each role's system prompt from its spec and its neighbours in the team.
- Check every role's output against its declared contract, and stop the pipeline when one is broken.

## The Problem

Multi-agent frameworks make it easy to declare a team: "You are a world-class researcher", "You are a meticulous editor". Personas like that describe a mood, not a job. They don't say what the researcher must hand over, who uses it, or when the editor should stop editing. So teams drift. The editor rewrites the draft itself, and now two agents own the same document. The researcher produces SEO keywords nobody reads. The writer can publish, because it was given the publishing tool "just in case". The writer and editor send drafts back and forth forever.

All of these are design bugs, visible on paper before any model runs. They're cheap to find if roles are written down in a form code can check.

## The Concept

```
 brief ─► researcher ──research_notes──► writer ──draft──► editor ──edit_notes──┐
                │                          ▲                                      │
                └──────research_notes──────┼──────────────► fact_checker ◄────────┘
                                           └──edit_notes (≤ 2 rounds)   │
                                                                approval ▼
                                                                   publisher ──► published
```

| Spec field | Answers | Linted for |
|------------|---------|------------|
| `goal` | What does success look like? | Vague words, too short to be specific |
| `inputs` | What does it need, from whom? | Inputs nobody produces |
| `outputs` (with fields) | What must it hand over? | Two owners of one artifact; outputs nobody uses |
| `tools` | What can it touch? | Side-effect tools it doesn't need |
| `done_when` | When does it stop? | Missing |
| `max_revisions` | How many rounds in a loop? | Loops without a limit |

**One owner per artifact.** If two roles can produce the draft, nobody knows which version is current, and each will undo the other. The editor's job is to return `edit_notes`; the writer owns the draft.

**Specialize by information and permission, not by adjective.** A good specialist has a narrower context (only the inputs it needs), a narrower tool set, and a checkable output. That's what makes it better than a generalist (Lesson 1), not being told it's an expert.

## Build It

```bash
cd code
python3 main.py
```

No model is needed: specs, the linter and the prompt generator are plain code. The pipeline run uses scripted outputs, two of which break their contracts on purpose.

### Step 1: roles as data

```python
Role("editor", "Check the draft against the brief and style guide; list required changes or approve.",
     ["draft", "brief"], {"edit_notes": ["changes", "approved"]}, [],
     "Either approved=true or a list of specific changes.", max_revisions=2)
```

### Step 2: lint the first draft of the team

```text
Lint: first draft of the team
  - overlap: 'draft' is produced by ['writer', 'editor']; one owner per artifact
  - orphan output: 'seo_keywords' from researcher is used by nobody
  - missing input: ['publisher'] need 'approval' but no role produces it
  - writer: vague goal 'Write the launch post.'
  - writer: has side-effect tool 'publish_post' it doesn't need for its outputs
  - editor: no done condition (when does it stop?)
  - editor: vague goal 'Make it good.'
  - loop: editor <-> writer with no revision limit
```

Each line is a real failure mode. The missing `approval` means the publisher either waits forever or someone hacks around it, which usually means publishing unchecked. The fix was a new role (`fact_checker`) that owns `approval`, not more instructions to the publisher.

```text
Lint: revised team
  no problems
```

### Step 3: prompts from specs

```python
def system_prompt(role, team):
    lines = [f"You are the {role.name}. Goal: {role.goal}",
             "You receive: " + ", ".join(f"{i} (from {who_makes.get(i, 'the user')})" for i in role.inputs) + ".",
             "You must return JSON with: " + ...,
```

```text
Generated system prompt for the editor (from its spec)
  | You are the editor. Goal: Check the draft against the brief and style guide; list required changes or approve.
  | You receive: draft (from writer), brief (from the user).
  | You must return JSON with: edit_notes {changes, approved} (used by writer, fact_checker).
  | Tools: none. Do not do other roles' work.
  | You are done when: Either approved=true or a list of specific changes.
  | At most 2 revision rounds; then return your best version and say what's unresolved.
```

The prompt tells the editor who its work is for. That's information a persona never carries, and it changes behaviour: knowing the fact-checker reads `edit_notes`, the editor has a reason to be specific. Because the prompt is generated, changing the team updates every affected prompt.

### Step 4: contracts at runtime

```text
Pipeline run with contract checks (scripted outputs)
  researcher    ok
  writer        ok
  editor        CONTRACT BROKEN: produced artifacts it doesn't own: ['draft']
  fact_checker  CONTRACT BROKEN: 'approval' missing fields ['unsupported_claims']
  publisher     not run: its input 'approval' failed its contract
```

The specs pass lint, but a model can still ignore them. The editor rewrote the draft anyway; the fact-checker approved without listing what it checked. Checking each output against the spec (Phase 1 · Lesson 7) catches that at the handoff, and the pipeline stops before the side effect.

### Step 5: permissions follow the spec

```text
Permissions by role
  researcher    tools=['web_search']  side effects=-
  writer        tools=-  side effects=-
  editor        tools=-  side effects=-
  fact_checker  tools=-  side effects=-
  publisher     tools=['publish_post']  side effects=['publish_post']
```

Exactly one role can change the outside world, and it only runs on a passing approval.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Framework | Where the spec lives |
|-----------|---------------------|
| CrewAI | `role`, `goal`, `backstory` on agents; `expected_output` and `output_pydantic` on tasks |
| OpenAI Agents SDK | `instructions`, `tools`, `output_type`, `handoffs` per agent |
| LangGraph | Node functions with typed state in and out |
| Your own | A YAML or JSON file per team, linted in CI like any other config |

Whatever the framework, keep the contract fields (inputs, outputs, tools, done) in data, not only inside prompt prose.

## Ship It

`outputs/skill-agent-role-spec.md` is a skill for designing a team of roles: a spec template, the lint rules, prompt generation from specs, runtime contract checks at every handoff, and least-privilege tools per role.

## Exercises

1. **Easy.** Add an `seo` role that consumes `research_notes` and produces `seo_keywords` used by the writer. What does the lint say now?
2. **Medium.** Add a rule: every role's output fields must be mentioned in the done condition or the goal. Which revised roles fail it? Is the rule useful?
3. **Medium.** Make `check_output` also validate field types (lists vs strings vs booleans) from the spec. Which spec format change does that need?
4. **Hard.** Drive the revised team with a real model using the generated prompts and JSON output (Phase 1 · Lesson 6). Count contract breaks per role over 10 briefs, then tighten the prompts that break most.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Role spec | "Agent definition" | Goal, inputs, outputs, tools, permissions and stop condition for one agent, as data |
| Persona | "You are an expert…" | Tone and framing; not a contract |
| Artifact ownership | "Single writer" | Exactly one role may produce each artifact type |
| Orphan output | "Dead work" | Something a role produces that no other role or final output uses |
| Contract check | "Output validation" | Checking a role's output against its spec before the next role uses it |

## Further Reading

- [CrewAI, Agents and Tasks](https://docs.crewai.com/concepts/agents)
- [OpenAI Agents SDK, Agents](https://openai.github.io/openai-agents-python/agents/)
- [Anthropic, Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Cemri et al., Why Do Multi-Agent LLM Systems Fail? (2025)](https://arxiv.org/abs/2503.13657)
