---
name: guardrail-design
description: >
  Design and measure input and output guardrails for an LLM agent: choose rails per stage
  (redact before the model, tripwires in parallel, grounding on outputs), choose actions
  (allow, redact, flag, block), and build a labelled set to report precision and recall per
  rail. Use when adding guardrails, when users complain about refusals, or before turning a
  rail from flag to block.
---

# Guardrail design

## 1. Pick rails by stage

| Stage | Candidates |
|-------|------------|
| before the model | PII and secret redaction |
| parallel tripwire | topic scope, harmful content, abuse |
| flag only | jailbreak / injection patterns |
| on the answer | grounding of ids, amounts, dates and statuses against tool results; PII leaks; commitments policy forbids |

## 2. Pick actions
Default to redact or flag. Use block only for rails you have measured, and give every
block a safe reply that tells the user what you *can* help with.

## 3. Labelled set
At least 10 examples per rail: obvious positives, obvious negatives, and hard cases
(words with two meanings, numbers that look like cards, paraphrases). Pull real
examples from logs once you have them.

## 4. Report

| rail | tp | fp | fn | precision | recall | added latency |

List every false positive verbatim. Those are the customers you'd turn away.

## 5. Operate
Log every non-allow decision with the rail name and reason. Re-run the set whenever a
rail, its threshold or the model changes.
