"""The same agent on the real LlamaIndex library. Optional: not part of the tests.

    pip install -r requirements.txt
    python3 with_llamaindex.py

Runs offline: a scripted CustomLLM answers both the ReAct steps and the query engine's synthesis call.
A SummaryIndex is used so no embedding model is needed (it sends every chunk; fine for one small doc).
"""
from __future__ import annotations

import asyncio
from typing import Any

from llama_index.core import Document, Settings, SummaryIndex
from llama_index.core.agent.workflow import ReActAgent
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.llms import CompletionResponse, CompletionResponseGen, CustomLLM, LLMMetadata
from llama_index.core.llms.callbacks import llm_completion_callback
from llama_index.core.tools import FunctionTool, QueryEngineTool

from main import DEMO_REPLIES, HR_DOCS, subtract

PROMPTS: list[str] = []
QUEUE = list(DEMO_REPLIES)


class ScriptedLLM(CustomLLM):
    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(model_name="scripted", is_chat_model=False)

    @llm_completion_callback()
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        PROMPTS.append(prompt)
        return CompletionResponse(text=QUEUE.pop(0))

    @llm_completion_callback()
    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponseGen:
        text = self.complete(prompt).text
        yield CompletionResponse(text=text, delta=text)


async def main() -> None:
    llm = ScriptedLLM()
    Settings.llm, Settings.embed_model = llm, MockEmbedding(embed_dim=8)
    docs = [Document(text=d.text, metadata={"source": d.source}) for d in HR_DOCS]
    hr = QueryEngineTool.from_defaults(SummaryIndex.from_documents(docs).as_query_engine(llm=llm),
                                       name="hr_policies", description="HR policies: vacation, sick leave, benefits.")
    agent = ReActAgent(tools=[hr, FunctionTool.from_defaults(subtract)], llm=llm, streaming=False)
    answer = await agent.run("I've used 9 vacation days. How many are left?")
    print(f"answer: {answer}")
    print(f"model calls: {len(PROMPTS)}")
    print(f"\n--- the query engine's prompt ---\n{PROMPTS[1]}")


if __name__ == "__main__":
    asyncio.run(main())
