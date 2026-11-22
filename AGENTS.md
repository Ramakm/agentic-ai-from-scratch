# AGENTS.md

Instructions for AI coding agents working in this repository.

## What this repo is

A free course, **Agentic AI from Scratch**: 16 phases, 163 lessons, which teaches agents by building
every pattern by hand before using frameworks. The website in `site/` is generated from the
same content.

## Layout

| Path | What |
|------|------|
| `curriculum.json` | Source of truth: phases, lesson ids, titles, minutes, maintainer info |
| `phases/<phase>/<lesson>/` | One lesson: `docs/en.md`, `code/`, `quiz.json`, `outputs/` |
| `skills/<name>/SKILL.md` | Tutor skills installed with `npx skills add Ramakm/agentic-ai-from-scratch` |
| `scripts/build.mjs` | Generates site data, README contents, ROADMAP, phase READMEs, llms.txt |
| `scripts/test_lessons.py` | Runs every lesson's tests in isolation |
| `site/` | Static website (HTML/CSS/JS, no framework) |

## Rules

- A lesson is **live** if and only if `docs/en.md` exists. Never create a placeholder `docs/en.md`.
- Follow [LESSON_TEMPLATE.md](LESSON_TEMPLATE.md) exactly. The site parses the header lines.
- Lesson code must run offline with a scripted model and pass its tests with no network.
- Don't hand-edit generated files. Run `node scripts/build.mjs`.
- Before finishing: `python3 scripts/test_lessons.py` and `node scripts/build.mjs --check` must pass.
- Never commit secrets, `.env` files, or API keys. Lesson code reads keys only from env vars.
- Don't claim results you didn't run. If a lesson shows model output, it must be real output.

## Commands

```bash
python3 scripts/test_lessons.py           # all lesson tests
node scripts/build.mjs                    # regenerate derived files
node scripts/build.mjs --check            # CI check: stale files + structure + quiz validation
python3 -m http.server -d site 8000       # preview the site
```
