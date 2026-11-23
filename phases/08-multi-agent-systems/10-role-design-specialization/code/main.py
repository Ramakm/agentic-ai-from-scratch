"""Role design and specialization: write each agent's role as a spec (goal, inputs, outputs, tools,
permissions, done condition), lint the team for gaps and overlaps, generate prompts from the spec,
and check every role's output against what it promised.

    python3 main.py

No model needed: specs, the linter and the prompt generator are plain code. The pipeline run uses
scripted role outputs, one of which breaks its contract on purpose.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SIDE_EFFECT_TOOLS = {"publish_post", "send_email", "delete_file", "merge_pr", "charge_card"}
VAGUE = ("make it good", "do your best", "help with", "handle stuff", "as needed")


@dataclass
class Role:
    name: str
    goal: str
    inputs: list[str]                       # artifact types it needs
    outputs: dict[str, list[str]]           # artifact type -> required fields
    tools: list[str] = field(default_factory=list)
    done_when: str = ""
    approved_side_effects: list[str] = field(default_factory=list)  # side-effect tools this role is meant to own
    max_revisions: int | None = None        # for roles in a revision loop


# --------------------------------------------------------------------------------------------
# Two versions of the same team
# --------------------------------------------------------------------------------------------

FIRST_DRAFT = [
    Role("researcher", "Find facts and sources about the product launch.", ["brief"],
         {"research_notes": ["facts", "sources"], "seo_keywords": ["keywords"]}, ["web_search"],
         "Five sourced facts."),
    Role("writer", "Write the launch post.", ["brief", "research_notes", "edit_notes"],
         {"draft": ["title", "body"]}, ["web_search", "publish_post"], "A complete draft."),
    Role("editor", "Make it good.", ["draft"], {"draft": ["title", "body"], "edit_notes": ["changes"]}, [], ""),
    Role("publisher", "Publish the post once it has been approved.", ["draft", "approval"], {"published": ["url"]},
         ["publish_post"], "The post is live.", approved_side_effects=["publish_post"]),
]

REVISED = [
    Role("researcher", "Find 5 verifiable facts about the launch, each with a source URL.", ["brief"],
         {"research_notes": ["facts", "sources"]}, ["web_search"], "Five facts, each with a source."),
    Role("writer", "Turn the brief and research notes into a 600-800 word post using only sourced facts.",
         ["brief", "research_notes", "edit_notes"], {"draft": ["title", "body", "version"]}, [],
         "A draft within length that uses only facts from research_notes.", max_revisions=2),
    Role("editor", "Check the draft against the brief and style guide; list required changes or approve.",
         ["draft", "brief"], {"edit_notes": ["changes", "approved"]}, [],
         "Either approved=true or a list of specific changes.", max_revisions=2),
    Role("fact_checker", "Confirm every claim in the approved draft appears in research_notes with a source.",
         ["draft", "research_notes", "edit_notes"], {"approval": ["approved", "unsupported_claims"]}, [],
         "Every claim checked; unsupported claims listed."),
    Role("publisher", "Publish the draft only when the fact-checker approves it.", ["draft", "approval"],
         {"published": ["url"]}, ["publish_post"], "The post is live and its URL recorded.",
         approved_side_effects=["publish_post"]),
]
EXTERNAL_INPUTS = {"brief"}
FINAL_OUTPUTS = {"published"}


# --------------------------------------------------------------------------------------------
# Lint
# --------------------------------------------------------------------------------------------


def lint(team: list[Role]) -> list[str]:
    problems = []
    producers: dict[str, list[str]] = {}
    consumers: dict[str, list[str]] = {}
    for r in team:
        for out in r.outputs:
            producers.setdefault(out, []).append(r.name)
        for inp in r.inputs:
            consumers.setdefault(inp, []).append(r.name)
    for art, who in sorted(producers.items()):
        if len(who) > 1:
            problems.append(f"overlap: '{art}' is produced by {who}; one owner per artifact")
        if art not in consumers and art not in FINAL_OUTPUTS:
            problems.append(f"orphan output: '{art}' from {who[0]} is used by nobody")
    for art, who in sorted(consumers.items()):
        if art not in producers and art not in EXTERNAL_INPUTS:
            problems.append(f"missing input: {who} need '{art}' but no role produces it")
    for r in team:
        if not r.done_when:
            problems.append(f"{r.name}: no done condition (when does it stop?)")
        if any(v in r.goal.lower() for v in VAGUE) or len(r.goal.split()) < 5:
            problems.append(f"{r.name}: vague goal '{r.goal}'")
        for t in r.tools:
            if t in SIDE_EFFECT_TOOLS and t not in r.approved_side_effects:
                problems.append(f"{r.name}: has side-effect tool '{t}' it doesn't need for its outputs")
    # revision loops: A consumes B's output and B consumes A's output
    for a in team:
        for b in team:
            if a.name < b.name and set(a.outputs) & set(b.inputs) and set(b.outputs) & set(a.inputs):
                if a.max_revisions is None or b.max_revisions is None:
                    problems.append(f"loop: {a.name} <-> {b.name} with no revision limit")
    return problems


# --------------------------------------------------------------------------------------------
# Prompts from specs, and contract checks on outputs
# --------------------------------------------------------------------------------------------


def system_prompt(role: Role, team: list[Role]) -> str:
    who_makes = {o: r.name for r in team for o in r.outputs}
    who_uses = {}
    for r in team:
        for i in r.inputs:
            who_uses.setdefault(i, []).append(r.name)
    lines = [f"You are the {role.name}. Goal: {role.goal}",
             "You receive: " + ", ".join(f"{i} (from {who_makes.get(i, 'the user')})" for i in role.inputs) + ".",
             "You must return JSON with: " + "; ".join(
                 f"{o} {{{', '.join(f)}}} (used by {', '.join(who_uses.get(o, ['the final output']))})"
                 for o, f in role.outputs.items()) + ".",
             f"Tools: {', '.join(role.tools) or 'none'}. Do not do other roles' work.",
             f"You are done when: {role.done_when}"]
    if role.max_revisions:
        lines.append(f"At most {role.max_revisions} revision rounds; then return your best version and say what's unresolved.")
    return "\n".join(lines)


def check_output(role: Role, output: dict) -> list[str]:
    errs = []
    for art, fields in role.outputs.items():
        if art not in output:
            errs.append(f"missing artifact '{art}'")
            continue
        missing = [f for f in fields if f not in output[art]]
        if missing:
            errs.append(f"'{art}' missing fields {missing}")
    extra = set(output) - set(role.outputs)
    if extra:
        errs.append(f"produced artifacts it doesn't own: {sorted(extra)}")
    return errs


SCRIPTED = {
    "researcher": {"research_notes": {"facts": ["ships Dec 3", "exports to CSV and Parquet"],
                                      "sources": ["https://example.com/launch"]}},
    "writer": {"draft": {"title": "Exports are here", "body": "...", "version": 1}},
    "editor": {"edit_notes": {"changes": [], "approved": True},
               "draft": {"title": "Exports are finally here!", "body": "...", "version": 2}},  # rewrites the draft itself
    "fact_checker": {"approval": {"approved": True}},                                          # forgets a field
    "publisher": {"published": {"url": "https://blog.example.com/exports"}},
}


def main() -> None:
    print("Lint: first draft of the team")
    for p in lint(FIRST_DRAFT):
        print(f"  - {p}")
    print("\nLint: revised team")
    print("  " + ("\n  ".join(lint(REVISED)) or "no problems"))

    print("\nGenerated system prompt for the editor (from its spec)")
    for line in system_prompt(REVISED[2], REVISED).splitlines():
        print(f"  | {line}")

    print("\nPipeline run with contract checks (scripted outputs)")
    for role in REVISED:
        errs = check_output(role, SCRIPTED[role.name])
        print(f"  {role.name:<13} {'ok' if not errs else 'CONTRACT BROKEN: ' + '; '.join(errs)}")
        if errs and role.name == "fact_checker":
            print("  publisher     not run: its input 'approval' failed its contract")
            break

    print("\nPermissions by role")
    for role in REVISED:
        side = [t for t in role.tools if t in SIDE_EFFECT_TOOLS]
        print(f"  {role.name:<13} tools={role.tools or '-'}  side effects={side or '-'}")


if __name__ == "__main__":
    main()
