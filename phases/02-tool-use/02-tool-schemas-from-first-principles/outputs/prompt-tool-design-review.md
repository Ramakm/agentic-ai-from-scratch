# Prompt: Tool Design Review

Paste this prompt, followed by one or more tool definitions (OpenAI, Anthropic, or MCP format), into any capable model.

---

You are reviewing tool definitions that an LLM agent will call. The model only sees each tool's **name**, **description**, and **parameter JSON Schema**, never the implementation. Review each tool against this checklist and return concrete rewrites, not general advice.

1. **Name.** Is it a clear `verb_noun` (e.g. `search_flights`)? Could it be confused with another tool in the set?
2. **Description.** Does the first sentence say *what it does* and *when to use it*? Does it say when *not* to use it, if that's ambiguous?
3. **Parameter descriptions.** Does every parameter state its format with an example (`"IATA code, e.g. BLR"`, `"YYYY-MM-DD"`)?
4. **Types.** Is anything typed `string` that should be an `enum`, `integer`, `boolean`, or `array`? Are there unions the model will struggle with?
5. **Required vs optional.** Is `required` correct? Do optional fields have sensible defaults?
6. **Strictness.** Is `additionalProperties: false` set? Is the schema valid for strict / structured-output modes?
7. **Size.** Could this tool be split (too many parameters) or merged with another (near-duplicates)?
8. **Errors.** What will the model see when a call fails? Suggest specific, per-field error strings it can act on.

Output format, per tool:

- **Verdict:** ship / fix first
- **Problems:** a numbered list, each tied to a checklist item
- **Rewritten definition:** the full corrected JSON

---

Source: Agentic AI from Scratch, Phase 2, Lesson 2.
