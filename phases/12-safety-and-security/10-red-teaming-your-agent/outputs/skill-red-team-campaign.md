---
name: red-team-campaign
description: >
  Plan and run a red-team campaign against an LLM agent: derive goals from the threat model,
  build an attack grid (goals x framings x mutations), write side-effect judges with canaries,
  report attack success rate by slice, and keep successful attacks as a regression suite.
  Use before launch, after changing defences, tools or models, and on a schedule.
---

# Red-team campaign

## 1. Goals (from the threat model)
One goal per attack path that matters: exfiltrate via each egress channel, each
irreversible action (delete, pay, publish, message), cross-tenant access. Plant a
canary in the private data each exfiltration goal targets.

## 2. Grid
- framings: override, fake authority, helpful reminder, embedded in the task, role-play
- mutations: plain, base64/hex, homoglyphs, hidden markup (HTML comments, white text,
  alt text), split across sources, translation
- entry points: every untrusted source (docs, email, web, tool results, MCP servers)

## 3. Judges
Side effects only: request received with the canary, file gone, payment created,
message posted. Use an LLM judge only for harms with no side effect.

## 4. Run and read

| version | ASR | by goal | by framing | by mutation |

A goal near 100% = a capability no defence covers. A mutation far above plain = a
surface-text filter. A framing far above override = refusal training gap.

## 5. Fix and lock
Save every successful attack (exact inputs) to a regression file. The fix is done when
the whole file fails and the utility tasks still pass. Run both on every change.
