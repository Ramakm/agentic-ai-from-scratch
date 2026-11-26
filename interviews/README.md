# Interview questions

Practice questions for AI agent and LLM engineering interviews, published at
[/interviews/](https://agentic-ai-from-scratch.vercel.app/interviews/). Each question links to the
lessons that teach it.

- `cards.json` lists the topics, in display order.
- `<card>/<NN-slug>.md` is one question. The slug becomes the URL: `/interviews/<card>/<slug>/`.
- `node scripts/build.mjs` renders the pages; `node scripts/build.mjs --check` validates every file.

## Format

```markdown
# A title that states the situation, not "What is X?"

> The scenario, written as the interviewer would say it, ending with the question.

**Level:** 1 | 2 | 3 | 4
**Type:** Concept | Debug | Design | Trade-off | Estimate | Code
**Time:** ~N minutes
**Taught in:** 03-the-agent-loop/03-stop-conditions-max-steps, 03-the-agent-loop/12-debugging-a-stuck-loop

## Short answer

What a strong candidate says in the first minute. One paragraph.

## Full answer

### Subheadings, short paragraphs, a table where it helps

## Follow-ups

- **L3.** The next question an interviewer asks. *Expected:* what a good answer contains.

## Wrong answers

- "A plausible wrong answer, quoted." Why it's wrong.
```

Levels: 1 Fundamentals (screening), 2 Practitioner (has built agents), 3 Senior (owns a system),
4 Staff (sets direction across systems).

## Rules

- `Taught in` must name live lessons (`<phase-id>/<lesson-id>`). The build fails otherwise.
- Answers must agree with the lessons. If you cite a number, it must come from a lesson's real output
  or a linked source.
- Give at least two follow-ups and three wrong answers. Wrong answers should be ones people actually give.
