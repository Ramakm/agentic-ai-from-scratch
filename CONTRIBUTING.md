# Contributing

Thanks for helping build **Agentic AI from Scratch**. Most of the 163 lessons are planned but
not written yet, so the most valuable contribution is a lesson.

## Ways to help

| Contribution | How |
|--------------|-----|
| **Write a planned lesson** | Pick one from [ROADMAP.md](ROADMAP.md), open a "Lesson proposal" issue, follow [LESSON_TEMPLATE.md](LESSON_TEMPLATE.md) |
| **Fix a lesson** | Typos, wrong claims, broken code. Small PRs are welcome without an issue |
| **Report a bug** | Use the "Bug report" issue form; include the lesson id and your Python version |
| **Suggest a lesson** | Open an issue describing the problem it solves and where it fits |
| **Improve the site** | `site/` is plain HTML, CSS, and JS with no build framework |

## Ground rules for lessons

1. **Build before use.** Write the pattern by hand first (stdlib where possible), then show the framework.
2. **Runs offline.** `python3 code/main.py` must work with no API key, using a scripted model.
3. **Tested.** At least 5 unit tests that need no network.
4. **Honest.** If you ran it against a real model and it failed in an interesting way, show that.
   Don't polish away the failures.
5. **Ships something.** Every lesson leaves an artifact in `outputs/`.
6. **Primary sources.** Link papers and official docs in Further Reading.

## Workflow

```bash
git clone https://github.com/Ramakm/agentic-ai-from-scratch.git
cd agentic-ai-from-scratch
git checkout -b lesson/03-02-react

# write phases/03-the-agent-loop/02-react-reason-act-observe/...

python3 scripts/test_lessons.py 02-react      # run your lesson's tests
node scripts/build.mjs                        # regenerate README contents, ROADMAP, phase pages, site data
node scripts/build.mjs --check                # what CI runs
```

Commit the regenerated files with your lesson, then open a PR using the template.

### Preview the site locally

```bash
node scripts/build.mjs          # also copies lesson content into site/content/
python3 -m http.server -d site 8000
# open http://localhost:8000
```

## Changing the curriculum

`curriculum.json` is the single source of truth for phases, lesson ids, titles, and times.
Renaming or reordering lessons changes URLs and people's saved progress, so open an issue first.

Generated files (don't edit by hand): `README.md` between the `CONTENTS` markers, `ROADMAP.md`,
`phases/*/README.md`, `site/assets/data.js`, `site/llms.txt`.

## Style

- Plain, direct English. Short sentences. Explain jargon the first time it appears.
- Python: type hints, small functions, docstrings on anything a reader might call.
- No emojis in lesson text.

## Code of conduct

Be kind and assume good intent. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Questions? Open a discussion or reach the maintainer:

<a href="https://www.linkedin.com/in/ramakrushnamohapatra"><img src="assets/readme/icons/linkedin.svg" width="16" height="16" alt="LinkedIn"> ramakrushnamohapatra</a><br>
<a href="https://www.instagram.com/techwith.ram/"><img src="assets/readme/icons/instagram.svg" width="16" height="16" alt="Instagram"> techwith.ram</a><br>
<a href="https://x.com/techwith_ram"><img src="assets/readme/icons/x.svg" width="16" height="16" alt="X (Twitter)"> techwith_ram</a>
