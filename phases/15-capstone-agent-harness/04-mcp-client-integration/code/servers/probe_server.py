"""A minimal MCP server for tests: reports which environment variable names it can see, and can crash.

Tools: env_names (sorted variable names, never values), crash (exits the process mid-call).
"""
import json
import os
import sys

TOOLS = [{"name": "env_names", "description": "Names of the environment variables this server can see.",
          "inputSchema": {"type": "object", "properties": {}}},
         {"name": "crash", "description": "Exit without replying.", "inputSchema": {"type": "object", "properties": {}}}]

for line in sys.stdin:
    msg = json.loads(line)
    rid, method = msg.get("id"), msg.get("method")
    if rid is None:
        continue
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "probe"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call" and msg["params"]["name"] == "env_names":
        result = {"content": [{"type": "text", "text": ", ".join(sorted(os.environ))}]}
    elif method == "tools/call":
        print("probe: crashing on purpose", file=sys.stderr, flush=True)
        sys.exit(3)
    else:
        result = None
    out = {"jsonrpc": "2.0", "id": rid}
    out.update({"result": result} if result is not None else {"error": {"code": -32601, "message": "not found"}})
    print(json.dumps(out), flush=True)
