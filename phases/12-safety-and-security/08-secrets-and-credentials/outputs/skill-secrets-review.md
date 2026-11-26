---
name: secrets-review
description: >
  Review how an LLM agent handles credentials and fix it: find every way a secret can enter
  the model's context (prompt, tool args, tool results, files, env, traces), replace values
  with brokered handles bound to tool, argument and host, scrub results and logs, and shrink
  each credential's scope and lifetime. Use when an agent calls authenticated APIs, runs
  shell commands, or after a key appears in a transcript.
---

# Secrets review

## 1. Find values in the context
Search prompts, tool descriptions, few-shot examples, memory and traces for anything that
matches a credential pattern. Any hit: rotate it, then fix the path that put it there.

## 2. Broker
For each credential the agent needs:

| secret | tool(s) | argument | hosts / resources | lifetime | scope |
|--------|---------|----------|-------------------|----------|-------|

The model gets the handle name only. Substitution happens in code after the call is
written; refusals return an error the model can read.

## 3. Scrub
- every tool result: broker values + credential patterns, before the model reads it
- every log and trace, before it is written
- decide what happens on a hit: redact and alert

## 4. Processes
Shell and code tools get an allow-listed environment (PATH, LANG, a throwaway HOME).
Deny reads of `.env`, key files and cloud credential directories (permission rules).

## 5. Shrink the credential
Prefer per-user OAuth or app installation tokens, short-lived cloud credentials and
least-privilege DB roles. Note the blast radius of each secret if it leaked today.
