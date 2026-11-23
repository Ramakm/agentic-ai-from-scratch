# CrewAI Roles & Crews

> CrewAI turns three strings into a system prompt: "You are {role}. {backstory} Your personal goal is: {goal}". A task adds what to do, what a good answer looks like, and the previous task's output. A crew runs tasks in order or lets a manager assign them. Read the prompts it actually sends and you know exactly what you're paying for.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only; optional `with_crewai.py` needs `crewai`)
**Prerequisites:** Phase 9 · The same loop, ten frameworks; Phase 8 · Role design & specialization; Phase 8 · Supervisor hierarchies
**Time:** ~45 minutes

## Learning Objectives

- Rebuild CrewAI's agent, task and crew abstractions and the exact prompts they produce.
- Explain how a sequential crew passes context forward, and what a hierarchical manager adds.
- Capture and read the prompts a framework sends, using a recording model.
- Know CrewAI's defaults: `max_iter` 25, delegation off, memory off.

## The Problem

A role-based crew demos beautifully: a "Senior Researcher" with a rich backstory hands findings to an "Award-winning Writer", and out comes a report. Then it goes wrong in production. The writer ignores half the research, or the researcher loops on a tool, and nobody can say why, because the framework assembled the prompts and nobody has read them.

Every framework turns your configuration into prompts. If you can't see the prompt, you can't debug the agent. This lesson rebuilds CrewAI's core and, more importantly, puts the real prompts from a real CrewAI run on the page.

## The Concept

| CrewAI object | Fields that matter | Becomes |
|---------------|--------------------|---------|
| `Agent` | `role`, `goal`, `backstory`, `tools`, `max_iter` | The system prompt and the tool list |
| `Task` | `description`, `expected_output`, `agent`, `context` | The user prompt |
| `Crew` | `agents`, `tasks`, `process` | The order tasks run in and who does them |
| `kickoff(inputs)` | `{"topic": ...}` | Fills `{topic}` placeholders in goals and descriptions |

| Process | Who picks the agent | Context passed | Cost |
|---------|---------------------|----------------|------|
| `sequential` | You, per task | The previous task's output, automatically | One agent run per task |
| `hierarchical` | A manager model | What the manager delegates | Plus manager calls per task |

**What the prompts look like.** Captured from a real `crewai` 1.15.44 run (Step 6), the Writer's system and user messages are:

```text
[system]
You are Writer. You write plainly for busy engineers.
Your personal goal is: Write a one-line recommendation
[user]

Current Task: Write a recommendation from the research.

This is the expected criteria for your final answer: One sentence
you MUST return the actual complete content as the final answer, not a summary.

This is the context you're working with:
- CrewAI: roles, goals, backstories
- CrewAI: tasks state their expected output
- LangGraph: explicit graphs with checkpoints

Provide your complete response:
```

The role, backstory and goal are one short paragraph. The task's `expected_output` is the strongest lever you have over the answer's shape. And "context" is simply the previous output pasted in.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: agents become system prompts

```python
def system_prompt(self, inputs):
    return f"You are {self.role}. {self.backstory}\nYour personal goal is: {self.goal.format(**inputs)}"
```

### Step 2: tasks become user prompts

```python
prompt = (f"\nCurrent Task: {self.description.format(**inputs)}\n\n"
          f"This is the expected criteria for your final answer: {self.expected_output}\n"
          "you MUST return the actual complete content as the final answer, not a summary.\n")
if self.context:
    prompt += "\nThis is the context you're working with:\n" + "\n\n".join(t.output for t in self.context) + "\n"
```

A placeholder with no matching input fails with `KeyError: 'topic'`. Our tests hit exactly that while being written; CrewAI also needs every placeholder filled by `kickoff(inputs=...)`.

### Step 3: each task is a small tool loop

`execute()` is the Phase 3 loop bounded by `max_iter`, plus `final_answer()`, which keeps only the text after `Final Answer:` because models often answer in ReAct style.

### Step 4: the crew

```python
for i, task in enumerate(self.tasks):
    agent = self._assign(task, inputs)              # task.agent, or ask the manager
    if not task.context and self.process == "sequential" and i:
        task.context = [self.tasks[i - 1]]          # previous output flows forward
    task.output = execute(agent, task, llm, inputs, self.log)
```

In hierarchical mode `_assign` asks a manager model for JSON `{"coworker": "<role>"}` and falls back to the first agent on an invalid pick.

### Step 5: run it

```text
  task 1 -> Researcher
    Researcher used search_notes -> CrewAI: agents have role, goal, backstory; tasks have expect
  task 2 -> Writer

research output:
- CrewAI: roles, goals, backstories
- CrewAI: tasks state their expected output
- LangGraph: explicit graphs with checkpoints

final answer:
Prototype role-based teams in CrewAI; move to LangGraph when you need explicit control flow and durable state.
```

`main.py` then prints the Writer's prompt, built by our code. It's the same text as the real one above.

### Step 6: the real library, with a recording model

`with_crewai.py` runs the same crew on `crewai` 1.15.44 with a scripted `BaseLLM` subclass that records every prompt. It produced the same research, final answer and Writer prompt, in 3 model calls. When an agent has tools and the model doesn't support native function calling, CrewAI switches to a text ReAct format. This is the start of the Researcher's real system prompt:

```text
You are Researcher. You check sources and never guess.
Your personal goal is: Find facts about agent frameworks
You ONLY have access to the following tools, and should NEVER make up tools that are not listed here:

Tool Name: search_notes
Tool Arguments: { ...JSON schema... }
Tool Description: Search the team's notes.

IMPORTANT: Use the following format in your response:

Thought: you should always think about what to do
Action: the action to take, only one name of [search_notes], just the name, exactly as it's written.
Action Input: the input to the action, just a simple JSON object, enclosed in curly braces, using " to wrap keys and values.
Observation: the result of the action
```

That's Phase 3 · ReAct, generated for you. Small local models often break this format, which is a common source of "CrewAI is flaky" reports.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Lever | CrewAI | Advice |
|-------|--------|--------|
| Answer shape | `Task.expected_output`, `output_pydantic` | Be specific: format, length, fields |
| Loop budget | `Agent.max_iter` (default 25) | Lower it for agents with tools; 25 iterations is a lot of tokens |
| Delegation | `Agent.allow_delegation` (default False) | Turn on only when you've seen a need |
| Memory | `Crew(memory=...)` (default False) | Adds storage and extra prompt text |
| Manager | `Process.hierarchical` + `manager_llm` or `manager_agent` | Costs a call per assignment; measure it (Phase 8 · Cost of coordination) |
| Event-driven pipelines | CrewAI Flows | For control flow beyond one crew |
| Debugging | `verbose=True`, or a recording LLM like ours | Read the prompts |

## Ship It

`outputs/skill-crewai-crew-design.md` is a skill for designing a crew: one table of agents (role, goal, backstory, tools, `max_iter`), one table of tasks (description, expected output, agent, context), a choice of process with its cost, and a test that records and checks the prompts.

## Exercises

1. **Easy.** Make the Writer's `expected_output` demand "exactly one sentence under 25 words, no hedging". How does the user prompt change?
2. **Medium.** Add a third agent, an Editor, with `context=[t1, t2]`. Show the Editor's prompt. How much of it is repeated text?
3. **Medium.** Run the hierarchical crew and count model calls against sequential. What does the manager cost per task?
4. **Hard.** Point `main.py` at a small local model with `AGENT_BASE_URL`. Then switch to text ReAct like CrewAI's fallback and count how often the model breaks the `Action:` / `Action Input:` format over 20 runs.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Role / goal / backstory | "Agent persona" | Three strings joined into the system prompt |
| Expected output | "Task spec" | A sentence in the user prompt describing a good final answer |
| Context | "Task dependencies" | Earlier task outputs pasted into the prompt |
| Sequential process | "Pipeline" | Tasks run in list order; each sees the previous output |
| Hierarchical process | "Manager agent" | A manager model picks which agent handles each task |
| Recording model | "Prompt capture" | A model wrapper that stores every prompt the framework sends |

## Further Reading

- [CrewAI documentation](https://docs.crewai.com/)
- [CrewAI concepts: agents](https://docs.crewai.com/concepts/agents)
- [CrewAI concepts: tasks](https://docs.crewai.com/concepts/tasks)
- [CrewAI concepts: processes](https://docs.crewai.com/concepts/processes)
- [Yao et al., ReAct: Synergizing reasoning and acting in language models (2022)](https://arxiv.org/abs/2210.03629)
