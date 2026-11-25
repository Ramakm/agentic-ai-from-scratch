# Lesson Template

Copy this structure for every new lesson. A lesson goes **live** on the site the moment
`docs/en.md` exists, so don't merge a half-written one.

## Folder

```text
phases/<NN-phase-id>/<NN-lesson-id>/
├── docs/en.md          the lesson (format below)
├── code/main.py        runnable implementation, stdlib-first, offline by default
├── code/test_main.py   unittest suite: 5+ tests, no network, no API keys
├── quiz.json           6 questions: 1–2 pre, 3 check, 1–2 post
└── outputs/            at least one artifact: skill-*.md or prompt-*.md
```

The folder ids must match `curriculum.json` exactly.

## Code rules

- **Offline by default.** Use a scripted model (a function that replays fixed assistant
  messages) so `python3 code/main.py` runs with no keys and no network.
- **Real model with two env vars.** `AGENT_BASE_URL` + `AGENT_MODEL` (+ optional
  `AGENT_API_KEY`) against any OpenAI-compatible `/chat/completions` endpoint.
- **Inject the model.** Take `llm` as a parameter so tests can pass a fake.
- **Standard library first.** If you need a package, add `code/requirements.txt` and say so in the lesson header.
- **Errors are observations.** Tool failures return strings; they never crash the loop.
- **Never `eval` model output.** Treat tool arguments as untrusted input.
- Python 3.10+.

## docs/en.md format

```markdown
# <Lesson Title>

> <One-line motto, the idea that sticks.>

**Type:** Build | Learn
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** <Phase N · Lesson title>, or None
**Time:** ~<minutes> minutes

## Learning Objectives

- 3–4 bullets that start with a verb: Implement…, Explain…, Measure…

## The Problem

2–3 paragraphs. A concrete failure the learner has hit or will hit. No theory yet.

## The Concept

Tables and short sections. Build the mental model before any code.
Use tables or SVG for diagrams (no ASCII art).
SVG files go in `docs/assets/` and are linked as `![what it shows](assets/name.svg)`;
the build copies them to the site and `--check` fails on a missing one.

## Build It

Run-it-first command, then `### Step 1: …`, `### Step 2: …` walking through `code/main.py`.
Show real output. If you ran it against a real model, show what actually happened,
including failures. Those are the best teaching moments.
End with how to run the tests.

## Use It

How production frameworks do the same thing (a table works well).

## Ship It

What's in `outputs/` and how to use it.

## Exercises

1. **Easy.** …
2. **Medium.** …
3. **Medium.** …
4. **Hard.** …

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|

## Further Reading

- Primary sources first: papers, official docs.
```

The site parses the `# title`, the `>` motto, and the four `**Key:**` lines into the lesson
header, so keep them exactly in this shape.

## quiz.json format

```json
{
  "lesson": "<lesson-id>",
  "title": "<Lesson Title>",
  "questions": [
    {
      "stage": "pre",
      "question": "…",
      "options": ["…", "…", "…", "…"],
      "correct": 1,
      "explanation": "Why the right answer is right, in one or two sentences."
    }
  ]
}
```

`stage` is `pre` (asked before reading), `check` (during), or `post` (applied, after).
`correct` is the zero-based index into `options`.

## Before you open a PR

```bash
python3 scripts/test_lessons.py <your-lesson-id>   # your tests pass
node scripts/build.mjs                              # regenerates README, ROADMAP, phase pages, site data
node scripts/build.mjs --check                      # structure + quiz validation (same as CI)
```

Commit the regenerated files with your lesson.
