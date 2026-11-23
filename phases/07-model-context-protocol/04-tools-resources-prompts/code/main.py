"""Tools, resources and prompts: the three things an MCP server offers, and who decides when each is used.

A company-handbook server exposes:
  resources  handbook pages by URI, a URI template for policies, and a sandboxed folder of files
  prompts    templates the user picks (with arguments), embedding resources in the messages
  tools      a search the model can call, returning links to resources

A scripted host then shows the three control points: the application attaches a resource, the user
runs a prompt, the model calls a tool. Stdlib only, no network, no model.

    python3 main.py
"""
from __future__ import annotations

import base64
import os
import re
import tempfile
import urllib.parse

PROTOCOL_VERSION = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {}}


class RPCError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


PAGES = {
    "handbook://policies/expenses": ("Expense policy", "Meals: up to 40 EUR per day.\nHotels: up to 150 EUR per night.\n"
                                     "Receipts over 25 EUR are required."),
    "handbook://policies/travel": ("Travel policy", "Book economy for flights under 6 hours.\n"
                                   "Trains are preferred under 4 hours."),
    "handbook://it/vpn": ("VPN setup", "Install the WireGuard profile from the IT portal.\nUse SSO to sign in."),
}
LOGO_PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489")


# --------------------------------------------------------------------------------------------
# URI templates (RFC 6570, the two forms servers use most: {var} and {+var})
# --------------------------------------------------------------------------------------------


def template_regex(template: str) -> re.Pattern:
    parts, last = [], 0
    for m in re.finditer(r"\{(\+?)(\w+)\}", template):
        parts.append(re.escape(template[last:m.start()]))
        parts.append(f"(?P<{m.group(2)}>.+)" if m.group(1) else f"(?P<{m.group(2)}>[^/]+)")
        last = m.end()
    parts.append(re.escape(template[last:]))
    return re.compile("^" + "".join(parts) + "$")


def match_template(template: str, uri: str) -> dict | None:
    m = template_regex(template).match(uri)
    return {k: urllib.parse.unquote(v) for k, v in m.groupdict().items()} if m else None


# --------------------------------------------------------------------------------------------
# The handbook server
# --------------------------------------------------------------------------------------------


class HandbookServer:
    def __init__(self, files_root: str):
        self.files_root = os.path.realpath(files_root)

    def handle(self, method: str, params: dict) -> dict:
        try:
            fn = getattr(self, method.replace("/", "_"), None)
            if fn is None:
                raise RPCError(-32601, "Method not found")
            return {"result": {"resultType": "complete", **fn(params)}}
        except RPCError as e:
            return {"error": {"code": e.code, "message": e.message, **({"data": e.data} if e.data else {})}}

    def server_discover(self, params: dict) -> dict:
        return {"supportedVersions": [PROTOCOL_VERSION], "ttlMs": 3600000, "cacheScope": "public",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}}}

    # -- resources: application-controlled context --------------------------------------------
    def resources_list(self, params: dict) -> dict:
        items = [{"uri": u, "name": u.rsplit("/", 1)[1], "title": t, "mimeType": "text/markdown"}
                 for u, (t, _) in sorted(PAGES.items())]
        items.append({"uri": "handbook://assets/logo.png", "name": "logo.png", "mimeType": "image/png"})
        return {"resources": items, "ttlMs": 300000, "cacheScope": "public"}

    def resources_templates_list(self, params: dict) -> dict:
        return {"resourceTemplates": [
            {"uriTemplate": "handbook://policies/{name}", "name": "policy", "title": "Policy by name",
             "mimeType": "text/markdown"},
            {"uriTemplate": "file:///{+path}", "name": "shared-file", "title": "File in the shared handbook folder",
             "mimeType": "text/plain"}], "ttlMs": 300000, "cacheScope": "public"}

    def resources_read(self, params: dict) -> dict:
        uri = params.get("uri", "")
        if uri in PAGES:
            contents = [{"uri": uri, "mimeType": "text/markdown", "text": PAGES[uri][1]}]
        elif uri == "handbook://assets/logo.png":
            contents = [{"uri": uri, "mimeType": "image/png", "blob": base64.b64encode(LOGO_PNG).decode()}]
        elif (args := match_template("file:///{+path}", uri)) is not None:
            contents = [{"uri": uri, "mimeType": "text/plain", "text": self.read_shared(args["path"], uri)}]
        else:
            raise RPCError(-32602, "Resource not found", {"uri": uri})
        return {"contents": contents, "ttlMs": 60000, "cacheScope": "private"}

    def read_shared(self, path: str, uri: str) -> str:
        """Resolve inside the root or refuse. realpath follows '..' and symlinks before the check."""
        full = os.path.realpath(os.path.join(self.files_root, path))
        if os.path.commonpath([full, self.files_root]) != self.files_root:
            raise RPCError(-32602, "Resource not found", {"uri": uri})  # don't confirm what exists outside
        if not os.path.isfile(full):
            raise RPCError(-32602, "Resource not found", {"uri": uri})
        with open(full, encoding="utf-8") as f:
            return f.read()

    # -- prompts: user-controlled templates ----------------------------------------------------
    PROMPTS = [
        {"name": "summarize_policy", "title": "Summarize a policy",
         "description": "Summarize one handbook policy for an audience.",
         "arguments": [{"name": "policy", "description": "expenses or travel", "required": True},
                       {"name": "audience", "description": "who it's for (default: new joiners)", "required": False}]},
        {"name": "check_expense", "title": "Check an expense",
         "description": "Check an expense against the expense policy.",
         "arguments": [{"name": "amount_eur", "required": True}, {"name": "category", "required": True}]},
    ]

    def prompts_list(self, params: dict) -> dict:
        return {"prompts": self.PROMPTS, "ttlMs": 300000, "cacheScope": "public"}

    def prompts_get(self, params: dict) -> dict:
        name, args = params.get("name"), params.get("arguments") or {}
        spec = next((p for p in self.PROMPTS if p["name"] == name), None)
        if spec is None:
            raise RPCError(-32602, f"Unknown prompt: {name}")
        missing = [a["name"] for a in spec["arguments"] if a.get("required") and a["name"] not in args]
        if missing:
            raise RPCError(-32602, "Missing required arguments", {"missing": missing})
        if name == "summarize_policy":
            uri = f"handbook://policies/{args['policy']}"
            if uri not in PAGES:
                raise RPCError(-32602, f"Unknown policy: {args['policy']}")
            audience = args.get("audience", "new joiners")
            return {"description": f"Summary of the {args['policy']} policy", "messages": [
                {"role": "user", "content": {"type": "resource", "resource": {
                    "uri": uri, "mimeType": "text/markdown", "text": PAGES[uri][1]}}},
                {"role": "user", "content": {"type": "text", "text":
                    f"Summarize the policy above for {audience} in three bullet points."}}]}
        return {"description": "Expense check", "messages": [
            {"role": "user", "content": {"type": "resource", "resource": {
                "uri": "handbook://policies/expenses", "mimeType": "text/markdown",
                "text": PAGES["handbook://policies/expenses"][1]}}},
            {"role": "user", "content": {"type": "text", "text":
                f"Is a {args['amount_eur']} EUR {args['category']} expense within this policy? "
                "Answer yes or no, then quote the rule."}}]}

    # -- tools: model-controlled actions ------------------------------------------------------
    def tools_list(self, params: dict) -> dict:
        return {"tools": [{"name": "search_handbook", "description":
                           "Search the handbook. Returns links to matching pages; read them for details.",
                           "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}},
                                           "required": ["query"], "additionalProperties": False},
                           "annotations": {"readOnlyHint": True}}],
                "ttlMs": 300000, "cacheScope": "public"}

    def tools_call(self, params: dict) -> dict:
        if params.get("name") != "search_handbook":
            raise RPCError(-32602, f"Unknown tool: {params.get('name')}")
        words = params["arguments"]["query"].lower().split()
        links = [{"type": "resource_link", "uri": u, "name": u.rsplit("/", 1)[1], "title": t,
                  "mimeType": "text/markdown"}
                 for u, (t, body) in sorted(PAGES.items()) if any(w in (t + " " + body).lower() for w in words)]
        if not links:
            return {"content": [{"type": "text", "text": "No pages match."}], "isError": False}
        return {"content": [{"type": "text", "text": f"{len(links)} page(s) match."}, *links], "isError": False}


# --------------------------------------------------------------------------------------------
# Host side: a client with a TTL-respecting cache, and the three control points
# --------------------------------------------------------------------------------------------


class Client:
    def __init__(self, server: HandbookServer, clock=lambda: 0.0):
        self.server, self.clock = server, clock
        self.cache: dict = {}
        self.stats = {"hit": 0, "miss": 0}

    def request(self, method: str, params: dict | None = None, cache: bool = False) -> dict:
        key = (method, repr(sorted((params or {}).items())))
        hit = self.cache.get(key)
        if cache and hit and self.clock() < hit[0]:
            self.stats["hit"] += 1
            return hit[1]
        reply = self.server.handle(method, {**(params or {}), "_meta": META})
        if "error" in reply:
            raise RPCError(reply["error"]["code"], reply["error"]["message"], reply["error"].get("data"))
        result = reply["result"]
        if cache:
            self.stats["miss"] += 1
            self.cache[key] = (self.clock() + result.get("ttlMs", 0) / 1000, result)
        return result


def render_messages(messages: list[dict]) -> list[str]:
    out = []
    for m in messages:
        c = m["content"]
        if c["type"] == "text":
            out.append(f"{m['role']}: {c['text']}")
        else:
            out.append(f"{m['role']}: [embedded {c['resource']['uri']}, {len(c['resource']['text'])} chars]")
    return out


def make_shared_folder() -> tuple[str, str]:
    base = tempfile.mkdtemp(prefix="handbook-")
    root = os.path.join(base, "shared")
    os.makedirs(os.path.join(root, "forms"))
    with open(os.path.join(root, "forms", "leave.txt"), "w") as f:
        f.write("Leave request form: name, dates, manager.")
    with open(os.path.join(base, "payroll.csv"), "w") as f:
        f.write("name,salary\nana,72000")
    os.symlink(os.path.join(base, "payroll.csv"), os.path.join(root, "forms", "summary.txt"))
    return base, root


def main() -> None:
    base, root = make_shared_folder()
    server = HandbookServer(root)
    now = [0.0]
    client = Client(server, clock=lambda: now[0])
    caps = client.request("server/discover")["capabilities"]
    print(f"capabilities: {sorted(caps)}")

    print("\nResources (the application decides what to attach)")
    for r in client.request("resources/list", cache=True)["resources"]:
        print(f"  {r['uri']:<32} {r['mimeType']}")
    for t in client.request("resources/templates/list", cache=True)["resourceTemplates"]:
        print(f"  template {t['uriTemplate']:<27} {t['title']}")
    page = client.request("resources/read", {"uri": "handbook://policies/travel"}, cache=True)["contents"][0]
    print(f"  read handbook://policies/travel -> {page['text'].splitlines()[0]}")
    logo = client.request("resources/read", {"uri": "handbook://assets/logo.png"})["contents"][0]
    print(f"  read logo.png -> blob, {len(base64.b64decode(logo['blob']))} bytes, starts {base64.b64decode(logo['blob'])[:4]!r}")
    print(f"  template handbook://policies/{{name}} matches handbook://policies/travel: "
          f"{match_template('handbook://policies/{name}', 'handbook://policies/travel')}")

    print("\nSandboxed files behind file:///{+path}")
    for uri in ["file:///forms/leave.txt", "file:///../payroll.csv", "file:///forms/%2e%2e/%2e%2e/payroll.csv",
                "file:///forms/summary.txt", "file:///forms/missing.txt"]:
        try:
            text = client.request("resources/read", {"uri": uri})["contents"][0]["text"]
            print(f"  {uri:<44} -> {text}")
        except RPCError as e:
            print(f"  {uri:<44} -> {e.code} {e.message}")

    print("\nPrompts (the user picks one, like a slash command)")
    for p in client.request("prompts/list")["prompts"]:
        args = ", ".join(a["name"] + ("" if a.get("required") else "?") for a in p["arguments"])
        print(f"  /{p['name']}({args})  {p['description']}")
    got = client.request("prompts/get", {"name": "summarize_policy", "arguments": {"policy": "expenses"}})
    print("  /summarize_policy policy=expenses ->")
    for line in render_messages(got["messages"]):
        print(f"    {line}")
    for args in [{"amount_eur": "55"}, {"policy": "parking"}]:
        name = "check_expense" if "amount_eur" in args else "summarize_policy"
        try:
            client.request("prompts/get", {"name": name, "arguments": args})
        except RPCError as e:
            print(f"  /{name} {args} -> {e.code} {e.message} {e.data or ''}".rstrip())

    print("\nTools (the model decides when to call)")
    tool = client.request("tools/list")["tools"][0]
    print(f"  {tool['name']}: {tool['description']}")
    for q in ["receipts hotel", "parking"]:
        res = client.request("tools/call", {"name": "search_handbook", "arguments": {"query": q}})
        blocks = [b["text"] if b["type"] == "text" else f"link {b['uri']}" for b in res["content"]]
        print(f"  search_handbook({q!r}) -> {blocks}")

    print("\nCaching by ttlMs (page ttlMs=60000, list ttlMs=300000)")
    fresh = Client(server, clock=lambda: now[0])
    for t, method, params in [(0, "resources/read", {"uri": "handbook://policies/travel"}),
                              (30, "resources/read", {"uri": "handbook://policies/travel"}),
                              (61, "resources/read", {"uri": "handbook://policies/travel"}),
                              (61, "resources/list", None), (200, "resources/list", None),
                              (362, "resources/list", None)]:
        now[0] = t
        before = fresh.stats["hit"]
        fresh.request(method, params, cache=True)
        print(f"  t={t:>3}s {method:<15} {'hit' if fresh.stats['hit'] > before else 'miss (sent to server)'}")

if __name__ == "__main__":
    main()
