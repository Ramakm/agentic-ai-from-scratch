"""The same two-agent crew on the real CrewAI library. Optional: not part of the tests.

    pip install -r requirements.txt
    CREWAI_DISABLE_TELEMETRY=true OTEL_SDK_DISABLED=true python3 with_crewai.py

Runs offline with a scripted BaseLLM that also records the prompts CrewAI builds.
"""
from __future__ import annotations

from crewai import Agent, BaseLLM, Crew, Process, Task
from crewai.tools import tool

from main import search_notes as _search


class ScriptedLLM(BaseLLM):
    replies: list = []
    seen: list = []

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None):
        self.seen.append(messages)
        return self.replies.pop(0)

    def supports_function_calling(self) -> bool:
        return False          # CrewAI falls back to text ReAct: Thought / Action / Action Input / Final Answer


@tool("search_notes")
def search_notes(query: str) -> str:
    """Search the team's notes."""
    return _search(query)


llm = ScriptedLLM(model="scripted", replies=[
    'Thought: I should check the notes.\nAction: search_notes\nAction Input: {"query": "crewai and langgraph"}',
    "Thought: I have the facts.\nFinal Answer:\n- CrewAI: roles, goals, backstories\n"
    "- CrewAI: tasks state their expected output\n- LangGraph: explicit graphs with checkpoints",
    "Final Answer: Prototype role-based teams in CrewAI; move to LangGraph when you need explicit "
    "control flow and durable state.",
])

researcher = Agent(role="Researcher", goal="Find facts about {topic}", backstory="You check sources and never guess.",
                   tools=[search_notes], llm=llm, verbose=False)
writer = Agent(role="Writer", goal="Write a one-line recommendation", backstory="You write plainly for busy engineers.",
               llm=llm, verbose=False)
t1 = Task(description="List key facts about {topic}.", expected_output="3 bullet points", agent=researcher)
t2 = Task(description="Write a recommendation from the research.", expected_output="One sentence", agent=writer)

if __name__ == "__main__":
    crew = Crew(agents=[researcher, writer], tasks=[t1, t2], process=Process.sequential, verbose=False)
    out = crew.kickoff(inputs={"topic": "agent frameworks"})
    print(f"research output:\n{t1.output.raw}\n\nfinal answer:\n{out.raw}")
    print(f"\nmodel calls: {len(llm.seen)}")
    print("\n--- the prompt the Writer received ---")
    for m in llm.seen[-1]:
        print(f"[{m['role']}]\n{m['content']}")
