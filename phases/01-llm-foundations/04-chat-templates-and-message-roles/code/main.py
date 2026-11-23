"""Chat templates: the model never sees a list of messages. It sees one string with special tokens.

This file renders llama3.2's chat template by hand (the same template Ollama uses), plus ChatML for
comparison, and proves the rendering exact by sending it in raw mode and comparing token counts and
outputs with Ollama's own /api/chat.

    python3 main.py           # render a conversation in two template families
    python3 main.py --live    # verify the rendering against Ollama, then prefill a reply
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

# ---------------------------------------------------------------- llama 3.x, as in Ollama's template

H = "<|start_header_id|>{role}<|end_header_id|>"
EOT = "<|eot_id|>"
TOOL_PREAMBLE = ("Given the following functions, please respond with a JSON for a function call with its proper "
                 "arguments that best answers the given prompt.\n\nRespond in the format {\"name\": function name, "
                 "\"parameters\": dictionary of argument name and its value}. Do not use variables.\n\n")


def go_json(obj) -> str:
    """Ollama is written in Go; Go's encoder prints compact JSON with map keys sorted."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def tool_json(tool: dict) -> str:
    """Go marshals structs in field order (type, function{name, description, parameters{type, required, properties}})."""
    fn = tool["function"]
    params = fn.get("parameters", {})
    props = {k: {kk: v[kk] for kk in ("type", "description", "enum") if kk in v} for k, v in params.get("properties", {}).items()}
    ordered = {"type": "function", "function": {"name": fn["name"], "description": fn.get("description", ""),
               "parameters": {"type": params.get("type", "object"), "required": params.get("required", []),
                              "properties": props}}}
    return json.dumps(ordered, separators=(",", ":"), ensure_ascii=False)


def render_llama3(messages: list[dict], tools: list[dict] | None = None) -> str:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    out = H.format(role="system") + "\n\nCutting Knowledge Date: December 2023\n\n"
    if system:
        out += system
    if tools:
        out += ("When you receive a tool call response, use the output to format an answer to the orginal user "
                "question.\n\nYou are a helpful assistant with tool calling capabilities.")
    out += EOT
    turns = [m for m in messages if m["role"] != "system"]
    for i, m in enumerate(turns):
        last = i == len(turns) - 1
        if m["role"] == "user":
            out += H.format(role="user")
            if tools and last:                        # tools go ONLY into the final user message
                out += "\n\n" + TOOL_PREAMBLE + "".join(tool_json(t) + "\n" for t in tools) + "\n" + m["content"] + EOT
            else:
                out += "\n\n" + m["content"] + EOT
            if last:
                out += H.format(role="assistant") + "\n\n"
        elif m["role"] == "assistant":
            out += H.format(role="assistant")
            if m.get("tool_calls"):
                out += "\n" + "".join('\n{"name": "%s", "parameters": %s}' % (c["function"]["name"],
                                      go_json(json.loads(c["function"]["arguments"]) if isinstance(c["function"]["arguments"], str)
                                              else c["function"]["arguments"])) for c in m["tool_calls"])
            else:
                out += "\n\n" + m["content"]
            if not last:
                out += EOT
        elif m["role"] == "tool":                     # tool results are the "ipython" role in Llama 3
            out += H.format(role="ipython") + "\n\n" + m["content"] + EOT
            if last:
                out += H.format(role="assistant") + "\n\n"
    return out


def render_chatml(messages: list[dict]) -> str:
    """ChatML (Qwen, many fine-tunes): the same idea with different markers."""
    body = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
    return body + "<|im_start|>assistant\n"

# ---------------------------------------------------------------- conversations

SIMPLE = [{"role": "system", "content": "You are terse. Answer in at most five words."},
          {"role": "user", "content": "What is the capital of Australia?"}]
MULTI = SIMPLE + [{"role": "assistant", "content": "Canberra."},
                  {"role": "user", "content": "And of New Zealand?"}]
TOOLS = [{"type": "function", "function": {"name": "lookup", "description": "Look up a fact.", "parameters": {
    "type": "object", "properties": {"topic": {"type": "string", "description": "what to look up"}}, "required": ["topic"]}}}]
WITH_TOOLS = [{"role": "user", "content": "How tall is K2?"}]
AFTER_TOOL = WITH_TOOLS + [
    {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "lookup", "arguments": {"topic": "K2 height"}}}]},
    {"role": "tool", "content": "8611 metres"}]

# ---------------------------------------------------------------- live verification


def post(path: str, body: dict) -> dict:
    base = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def compare(name: str, messages: list[dict], tools: list[dict] | None, model: str) -> bool:
    opts = {"temperature": 0, "num_predict": 24}
    chat = post("/api/chat", {"model": model, "messages": messages, "tools": tools or [], "stream": False, "options": opts})
    raw = post("/api/generate", {"model": model, "prompt": render_llama3(messages, tools), "raw": True,
                                 "stream": False, "options": opts})
    chat_out = chat["message"].get("content") or go_json([c["function"] for c in chat["message"].get("tool_calls", [])])
    same = chat["prompt_eval_count"] == raw["prompt_eval_count"]
    print(f"{name:22} tokens chat={chat['prompt_eval_count']:4} ours={raw['prompt_eval_count']:4} "
          f"{'MATCH' if same else 'DIFFERENT'}\n{'':22} chat: {chat_out[:70]!r}\n{'':22} ours: {raw['response'][:70]!r}")
    return same


if __name__ == "__main__":
    if "--live" not in sys.argv:
        print("---- llama 3 ----")
        print(render_llama3(MULTI))
        print("\n---- ChatML ----")
        print(render_chatml(MULTI))
        print("\n---- llama 3, after a tool result (note: no tool list anywhere) ----")
        print(render_llama3(AFTER_TOOL, TOOLS))
        sys.exit()
    model = os.environ.get("AGENT_MODEL", "llama3.2")
    for name, msgs, tools in (("system + user", SIMPLE, None), ("multi-turn", MULTI, None),
                              ("user + tools", WITH_TOOLS, TOOLS), ("after a tool result", AFTER_TOOL, TOOLS)):
        compare(name, msgs, tools, model)
    prefill = render_llama3([{"role": "user", "content": "Name one city in Japan."}]) + '{"city": "'
    r = post("/api/generate", {"model": model, "prompt": prefill, "raw": True, "stream": False,
                               "options": {"temperature": 0, "num_predict": 20}})
    print(f"\nprefilled the reply with '{{\"city\": \"' -> model continued: {r['response']!r}")
