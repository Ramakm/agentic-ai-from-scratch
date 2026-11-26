---
name: injection-defence-review
description: >
  Review an LLM agent's defences against direct and indirect prompt injection. Finds where
  untrusted text enters, separates defences that lower the success rate from defences that
  make success harmless, and produces an attacks-vs-utility table. Use when adding a tool
  that reads external content, before launch, or after an injection incident.
---

# Prompt injection defence review

## 1. Entry points
List every place third-party text reaches the model: tool results, retrieved documents,
emails, web pages, file uploads, MCP servers, memories, other agents. Mark the user's own
messages separately (direct injection).

## 2. Direct injection
For every tool, ask: if the user asks for something they aren't allowed to have, does the
tool refuse on its own (ownership check, scoped credentials)? If the answer is "the prompt
tells the model not to", that's a finding.

## 3. Indirect injection: sort the defences

| Defence in place | Family |
|------------------|--------|
| keyword or classifier filter, delimiters, "treat tool output as data" | lowers the rate |
| approval for egress after untrusted content (taint) | makes success harmless |
| planner that never sees untrusted text (dual LLM, plan-then-execute) | makes success harmless |
| allow-listed URLs for tools and for rendered images/links | makes success harmless |

If every defence is in the first family, the agent has no guarantee. Say so.

## 4. Measure
Write at least 8 payloads: override, fake system note, polite paraphrase, encoded,
translated, split across two sources, data in a URL, markdown image. Write at least 2
legitimate tasks that read untrusted content and then act. Judge success by side effects
(requests received, emails sent), not by what the model said. Report:

| defence | attacks succeeded | legit tasks ok | approvals asked |

## 5. Recommend
Pick the cheapest change that takes attacks to zero against an obedient model while
keeping legitimate tasks working. Note the approval count; if it is high, flag fatigue.
