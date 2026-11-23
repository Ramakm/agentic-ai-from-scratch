---
name: skill-author
description: >
  Write or improve an Agent Skill (a folder with SKILL.md): a name that matches the
  folder, a description that says what it does and when to use it, a short body of
  steps, and long references moved into bundled files. Use when someone wants to
  turn a runbook, style guide or repeated workflow into a skill, or a skill isn't
  being picked up.
---

# Write a skill

## 1. Name and folder

- Lowercase letters, digits and hyphens, at most 64 characters: `release-notes`.
- The folder name is the same as `name`.

## 2. Description (the trigger)

One to three sentences, under 1024 characters:
- **What** it does, with the key nouns a user would say.
- **When** to use it: "Use when …" or a list of trigger phrases.
- What it's **not** for, if a neighbouring skill is easy to confuse with it.

Test it: would a model choose this skill from the description alone, for the right
tasks and not the wrong ones?

## 3. Body (level 2)

- Steps the agent follows, in order, short.
- Point to bundled files instead of inlining them: "Follow STYLE.md for formatting."
- Say what the output should look like.

## 4. Bundled files (level 3)

Long references, templates, examples, scripts. Each one is read only when the body
says so. Scripts should be runnable as-is.

## 5. Check

- Frontmatter parses; name matches the folder; description has a "when".
- Give 5 matching and 5 non-matching tasks to an agent with the skill installed; it
  should load the skill for the first five only.
