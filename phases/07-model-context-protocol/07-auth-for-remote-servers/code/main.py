"""Auth for remote MCP servers: the MCP server as an OAuth 2.1 resource server, discovery through
Protected Resource Metadata, authorization code + PKCE with the resource parameter, audience-bound
tokens, scope step-up, and the attacks each check stops.

    python3 main.py

Three small HTTP servers run on 127.0.0.1 with random ports: an authorization server, the notes MCP
server, and a downstream calendar API. The user's consent screen is simulated (there is no browser),
and fetching the client's metadata document is a dictionary lookup standing in for an HTTPS fetch.
Real deployments use HTTPS everywhere; plain http on localhost keeps this lesson offline.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.server
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL_VERSION = "2026-07-28"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --------------------------------------------------------------------------------------------
# Tokens: signed claims (a stand-in for a JWT; real servers use a JWT library or introspection)
# --------------------------------------------------------------------------------------------


def sign_token(claims: dict, key: bytes) -> str:
    body = b64url(json.dumps(claims, separators=(",", ":")).encode())
    return body + "." + b64url(hmac.new(key, body.encode(), hashlib.sha256).digest())


def verify_token(token: str, key: bytes) -> dict | None:
    try:
        body, sig = token.split(".")
    except ValueError:
        return None
    if not hmac.compare_digest(sig, b64url(hmac.new(key, body.encode(), hashlib.sha256).digest())):
        return None
    return json.loads(b64url_decode(body))


def pkce_pair() -> tuple[str, str]:
    verifier = b64url(secrets.token_bytes(32))
    return verifier, b64url(hashlib.sha256(verifier.encode()).digest())


# --------------------------------------------------------------------------------------------
# A tiny HTTP framework
# --------------------------------------------------------------------------------------------


class Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}

    def log_message(self, *args):
        pass

    def reply(self, status: int, body=None, headers: dict | None = None) -> None:
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self, verb: str) -> None:
        url = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(url.query))
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        fn = self.server.app.routes.get((verb, url.path))
        if fn is None:
            return self.reply(404, {"error": "not_found"})
        fn(self, query, raw)

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")


def start(app) -> str:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.app = app
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    app.base = f"http://127.0.0.1:{srv.server_address[1]}"
    return app.base


# --------------------------------------------------------------------------------------------
# Authorization server
# --------------------------------------------------------------------------------------------

# Client ID Metadata Documents: the client_id is an HTTPS URL; the AS fetches the JSON found there.
# This dict stands in for that fetch.
CLIENT_METADATA_DOCS = {
    "https://notes-app.example/oauth/client.json": {
        "client_id": "https://notes-app.example/oauth/client.json", "client_name": "Notes Desktop",
        "redirect_uris": ["http://127.0.0.1:53682/callback"], "grant_types": ["authorization_code"],
        "token_endpoint_auth_method": "none"},
}


class AuthServer:
    def __init__(self, signing_key: bytes, consent=lambda client, scopes: True):
        self.key, self.consent = signing_key, consent
        self.codes: dict[str, dict] = {}
        self.routes = {("GET", "/.well-known/oauth-authorization-server"): self.metadata,
                       ("GET", "/authorize"): self.authorize, ("POST", "/token"): self.token}

    def metadata(self, h, q, raw):
        h.reply(200, {"issuer": self.base, "authorization_endpoint": self.base + "/authorize",
                      "token_endpoint": self.base + "/token", "response_types_supported": ["code"],
                      "grant_types_supported": ["authorization_code"], "code_challenge_methods_supported": ["S256"],
                      "authorization_response_iss_parameter_supported": True,
                      "client_id_metadata_document_supported": True, "scopes_supported": ["notes:read", "notes:write"]})

    def authorize(self, h, q, raw):
        client = CLIENT_METADATA_DOCS.get(q.get("client_id", ""))
        if client is None or q.get("redirect_uri") not in client["redirect_uris"]:
            return h.reply(400, {"error": "invalid_request", "error_description": "unknown client or redirect_uri"})
        if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
            return h.reply(400, {"error": "invalid_request", "error_description": "PKCE S256 required"})
        if not q.get("resource"):
            return h.reply(400, {"error": "invalid_target", "error_description": "resource parameter required"})
        scopes = q.get("scope", "").split()
        if not self.consent(client["client_name"], scopes):  # the user's consent screen, simulated
            return h.reply(302, headers={"Location": q["redirect_uri"] + "?" + urllib.parse.urlencode(
                {"error": "access_denied", "state": q.get("state", ""), "iss": self.base})})
        code = secrets.token_urlsafe(16)
        self.codes[code] = {"client_id": q["client_id"], "redirect_uri": q["redirect_uri"], "scope": scopes,
                            "challenge": q["code_challenge"], "resource": q["resource"], "exp": time.time() + 60}
        h.reply(302, headers={"Location": q["redirect_uri"] + "?" + urllib.parse.urlencode(
            {"code": code, "state": q.get("state", ""), "iss": self.base})})

    def token(self, h, q, raw):
        form = dict(urllib.parse.parse_qsl(raw.decode()))
        grant = self.codes.pop(form.get("code", ""), None)  # pop: a code works once
        if grant is None or grant["exp"] < time.time():
            return h.reply(400, {"error": "invalid_grant", "error_description": "unknown, used or expired code"})
        if form.get("client_id") != grant["client_id"] or form.get("redirect_uri") != grant["redirect_uri"]:
            return h.reply(400, {"error": "invalid_grant", "error_description": "client or redirect_uri mismatch"})
        challenge = b64url(hashlib.sha256(form.get("code_verifier", "").encode()).digest())
        if not hmac.compare_digest(challenge, grant["challenge"]):
            return h.reply(400, {"error": "invalid_grant", "error_description": "PKCE verification failed"})
        if form.get("resource") != grant["resource"]:
            return h.reply(400, {"error": "invalid_target", "error_description": "resource differs from authorization"})
        claims = {"iss": self.base, "sub": "user-42", "aud": grant["resource"], "scope": " ".join(grant["scope"]),
                  "client_id": grant["client_id"], "exp": int(time.time()) + 600}
        h.reply(200, {"access_token": sign_token(claims, self.key), "token_type": "Bearer", "expires_in": 600,
                      "scope": claims["scope"]})

    def mint(self, **overrides) -> str:
        """For the attack demos: a token as this AS would issue it, with some claims changed."""
        claims = {"iss": self.base, "sub": "user-42", "aud": "?", "scope": "notes:read", "client_id": "x",
                  "exp": int(time.time()) + 600, **overrides}
        return sign_token(claims, self.key)


# --------------------------------------------------------------------------------------------
# Resource servers: the notes MCP server and a downstream calendar API
# --------------------------------------------------------------------------------------------

TOOL_SCOPES = {"search_notes": {"notes:read"}, "add_note": {"notes:write"}, "forward_to_calendar": {"notes:read"}}


class NotesMCPServer:
    def __init__(self, auth: AuthServer, key: bytes, calendar_url: str = ""):
        self.auth, self.key, self.calendar_url = auth, key, calendar_url
        self.notes = ["Q3 planning: book the offsite"]
        self.routes = {("GET", "/.well-known/oauth-protected-resource"): self.prm, ("POST", "/mcp"): self.mcp}

    @property
    def resource(self) -> str:  # canonical URI: scheme + host (+ port), no trailing slash
        return self.base

    def prm(self, h, q, raw):
        h.reply(200, {"resource": self.resource, "authorization_servers": [self.auth.base],
                      "scopes_supported": ["notes:read"], "bearer_methods_supported": ["header"]})

    def challenge(self, h, status: int, scope: str, error: str | None = None) -> None:
        parts = [f'error="{error}"'] if error else []
        parts += [f'resource_metadata="{self.base}/.well-known/oauth-protected-resource"', f'scope="{scope}"']
        h.reply(status, {"error": error or "unauthorized"}, {"WWW-Authenticate": "Bearer " + ", ".join(parts)})

    def mcp(self, h, q, raw):
        msg = json.loads(raw)
        auth = h.headers.get("Authorization", "")
        if "access_token" in q or not auth.startswith("Bearer "):  # never accept tokens from the query string
            return self.challenge(h, 401, "notes:read")
        claims = verify_token(auth[7:], self.key)
        if (claims is None or claims["iss"] != self.auth.base or claims["exp"] < time.time()
                or claims["aud"] != self.resource):  # audience: issued for THIS server
            return self.challenge(h, 401, "notes:read", "invalid_token")
        params = msg.get("params", {})
        if msg["method"] == "tools/call":
            needed = TOOL_SCOPES.get(params.get("name"), set())
            if not needed <= set(claims["scope"].split()):
                return self.challenge(h, 403, " ".join(sorted(needed)), "insufficient_scope")
            text = self.run(params["name"], params.get("arguments", {}), auth[7:])
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        else:
            result = {"tools": [{"name": n, "inputSchema": {"type": "object"}} for n in TOOL_SCOPES]}
        h.reply(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {"resultType": "complete", **result}})

    def run(self, name: str, args: dict, incoming_token: str) -> str:
        if name == "search_notes":
            return "; ".join(n for n in self.notes if args.get("query", "").lower() in n.lower()) or "none"
        if name == "add_note":
            self.notes.append(args["text"])
            return f"added note {len(self.notes)}"
        # The anti-pattern: passing the user's token for THIS server on to another API.
        req = urllib.request.Request(self.calendar_url + "/events", headers={"Authorization": "Bearer " + incoming_token})
        try:
            return "calendar said: " + urllib.request.urlopen(req).read().decode()
        except urllib.error.HTTPError as e:
            return f"calendar refused: {e.code}"


class CalendarAPI:
    def __init__(self, auth: AuthServer, key: bytes, check_audience: bool):
        self.auth, self.key, self.check_audience = auth, key, check_audience
        self.routes = {("GET", "/events"): self.events}

    def events(self, h, q, raw):
        claims = verify_token(h.headers.get("Authorization", "")[7:], self.key)
        if claims is None or (self.check_audience and claims["aud"] != self.base):
            return h.reply(401, {"error": "invalid_token"})
        h.reply(200, {"events": ["Mon 10:00 board meeting"]})


# --------------------------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------------------------


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(method: str, url: str, body: bytes | None = None, headers: dict | None = None) -> tuple[int, dict, dict]:
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        resp = OPENER.open(req)
        status, hdrs, raw = resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        status, hdrs, raw = e.code, dict(e.headers), e.read()
    return status, hdrs, json.loads(raw) if raw else {}


def parse_www_authenticate(value: str) -> dict:
    return dict(re.findall(r'(\w+)="([^"]*)"', value))


class OAuthMCPClient:
    CLIENT_ID = "https://notes-app.example/oauth/client.json"
    REDIRECT_URI = "http://127.0.0.1:53682/callback"

    def __init__(self, server_url: str, log=print):
        self.server_url, self.log = server_url, log
        self.token: str | None = None
        self.granted: set[str] = set()
        self.ids = 0

    def call(self, method: str, params: dict | None = None, max_auth_attempts: int = 2) -> dict:
        for _ in range(max_auth_attempts + 1):
            self.ids += 1
            body = json.dumps({"jsonrpc": "2.0", "id": self.ids, "method": method, "params": {
                **(params or {}), "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                                            "io.modelcontextprotocol/clientCapabilities": {}}}}).encode()
            headers = {"Content-Type": "application/json", "MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": method}
            if self.token:
                headers["Authorization"] = "Bearer " + self.token
            status, hdrs, resp = fetch("POST", self.server_url + "/mcp", body, headers)
            if status == 200:
                return resp["result"]
            challenge = parse_www_authenticate(hdrs.get("WWW-Authenticate", ""))
            self.log(f"{method} -> {status} {challenge.get('error', '')} scope=\"{challenge.get('scope', '')}\"".replace("  ", " "))
            if status not in (401, 403):
                raise RuntimeError(f"{status}: {resp}")
            # Step-up: ask for the union of what we had and what the challenge needs.
            self.authorize(challenge["resource_metadata"], self.granted | set(challenge.get("scope", "").split()))
        raise PermissionError(f"still not authorized for {method} after {max_auth_attempts} attempts")

    def authorize(self, prm_url: str, scopes: set[str]) -> None:
        _, _, prm = fetch("GET", prm_url)
        as_url = prm["authorization_servers"][0]
        self.log(f"  protected resource metadata: resource={self.short(prm['resource'])} "
                 f"authorization_servers=[{self.short(as_url)}]")
        meta = None
        for path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
            status, _, body = fetch("GET", as_url + path)
            if status == 200:
                meta, found = body, path
                break
        if meta is None or "S256" not in meta.get("code_challenge_methods_supported", []):
            raise RuntimeError("authorization server metadata missing or no PKCE S256 support")
        self.log(f"  authorization server metadata from {found}")
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(8)
        expected_issuer = meta["issuer"]  # recorded before redirecting, checked against iss on return
        query = urllib.parse.urlencode({
            "response_type": "code", "client_id": self.CLIENT_ID, "redirect_uri": self.REDIRECT_URI,
            "scope": " ".join(sorted(scopes)), "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256", "resource": prm["resource"]})
        self.log(f"  authorize: scope=\"{' '.join(sorted(scopes))}\" resource={self.short(prm['resource'])} PKCE S256")
        status, hdrs, body = fetch("GET", meta["authorization_endpoint"] + "?" + query)
        cb = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(hdrs.get("Location", "")).query))
        if cb.get("iss") != expected_issuer:
            raise RuntimeError("authorization response iss doesn't match the expected issuer (mix-up?)")
        if cb.get("state") != state or "code" not in cb:
            raise RuntimeError(f"authorization failed: {cb.get('error', body)}")
        form = urllib.parse.urlencode({"grant_type": "authorization_code", "code": cb["code"],
                                       "redirect_uri": self.REDIRECT_URI, "client_id": self.CLIENT_ID,
                                       "code_verifier": verifier, "resource": prm["resource"]}).encode()
        status, _, tok = fetch("POST", meta["token_endpoint"], form, {"Content-Type": "application/x-www-form-urlencoded"})
        if status != 200:
            raise RuntimeError(f"token request failed: {tok}")
        self.token, self.granted = tok["access_token"], set(tok["scope"].split())
        self.log(f"  token issued: scope=\"{tok['scope']}\" expires_in={tok['expires_in']}")

    @staticmethod
    def short(url: str) -> str:
        return re.sub(r"http://127\.0\.0\.1:\d+", lambda m: NAMES.get(m.group(0), m.group(0)), url)


NAMES: dict[str, str] = {}


def setup(check_calendar_audience: bool = True):
    key = secrets.token_bytes(32)  # shared by the AS and resource servers here; real systems use JWKS or introspection
    auth = AuthServer(key)
    start(auth)
    calendar = CalendarAPI(auth, key, check_calendar_audience)
    start(calendar)
    notes = NotesMCPServer(auth, key, calendar.base)
    start(notes)
    NAMES.update({auth.base: "<auth-server>", notes.base: "<notes-mcp>", calendar.base: "<calendar-api>"})
    return auth, notes, calendar


def mcp_status(server: NotesMCPServer, token: str | None, via_query: bool = False, tool: str = "search_notes") -> str:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": {"query": "q3"}}}).encode()
    url = server.base + "/mcp" + (f"?access_token={token}" if via_query else "")
    headers = {"Content-Type": "application/json"}
    if token and not via_query:
        headers["Authorization"] = "Bearer " + token
    status, hdrs, _ = fetch("POST", url, body, headers)
    err = parse_www_authenticate(hdrs.get("WWW-Authenticate", "")).get("error", "")
    return f"{status} {err}".strip()


def main() -> None:
    auth, notes, calendar = setup()
    print("First contact: no token")
    client = OAuthMCPClient(notes.base, log=lambda s: print("  " + s))
    r = client.call("tools/call", {"name": "search_notes", "arguments": {"query": "q3"}})
    print(f"  retry with token -> {r['content'][0]['text']}")

    print("\nStep-up: writing needs a scope we weren't given")
    r = client.call("tools/call", {"name": "add_note", "arguments": {"text": "Draft agenda"}})
    print(f"  retry with token -> {r['content'][0]['text']}")
    print(f"  granted now: {sorted(client.granted)}")

    print("\nWhat the MCP server rejects (status, error)")
    good = client.token
    tampered_body = b64url(json.dumps({**verify_token(good, auth.key), "scope": "notes:read notes:admin"},
                                      separators=(",", ":")).encode())
    cases = [
        ("valid token", good, False),
        ("no token", None, False),
        ("token sent in the query string", good, True),
        ("token minted for the calendar API (wrong audience)", auth.mint(aud=calendar.base), False),
        ("expired token", auth.mint(aud=notes.base, exp=int(time.time()) - 5), False),
        ("scope edited after signing", tampered_body + "." + good.split(".")[1], False),
        ("token from another issuer", sign_token({"iss": "https://evil.example", "aud": notes.base, "scope": "notes:read",
                                                  "exp": int(time.time()) + 60}, auth.key), False),
    ]
    for label, token, via_query in cases:
        print(f"  {label:<52} {mcp_status(notes, token, via_query)}")

    print("\nWhat the authorization server rejects")
    def code_for(resource: str) -> tuple[str, str]:
        verifier, challenge = pkce_pair()
        q = urllib.parse.urlencode({"response_type": "code", "client_id": OAuthMCPClient.CLIENT_ID,
                                    "redirect_uri": OAuthMCPClient.REDIRECT_URI, "scope": "notes:read", "state": "s",
                                    "code_challenge": challenge, "code_challenge_method": "S256", "resource": resource})
        _, hdrs, _ = fetch("GET", auth.base + "/authorize?" + q)
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(hdrs["Location"]).query))["code"], verifier

    def redeem(code: str, verifier: str, resource: str) -> str:
        form = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "client_id": OAuthMCPClient.CLIENT_ID,
                                       "redirect_uri": OAuthMCPClient.REDIRECT_URI, "code_verifier": verifier,
                                       "resource": resource}).encode()
        status, _, body = fetch("POST", auth.base + "/token", form, {"Content-Type": "application/x-www-form-urlencoded"})
        return f"{status} {body.get('error', 'ok')}" + (f": {body['error_description']}" if "error_description" in body else "")

    code, verifier = code_for(notes.base)
    print(f"  {'stolen code, attacker has no PKCE verifier':<52} {redeem(code, 'guess', notes.base)}")
    code, verifier = code_for(notes.base)
    print(f"  {'code redeemed for a different resource':<52} {redeem(code, verifier, calendar.base)}")
    code, verifier = code_for(notes.base)
    redeem(code, verifier, notes.base)
    print(f"  {'code used a second time':<52} {redeem(code, verifier, notes.base)}")
    status, _, body = fetch("GET", auth.base + "/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": OAuthMCPClient.CLIENT_ID, "redirect_uri": "https://evil.example/cb",
        "code_challenge": "x", "code_challenge_method": "S256", "resource": notes.base}))
    print(f"  {'redirect_uri not in the client metadata document':<52} {status} {body['error']}")

    print("\nToken passthrough: forward_to_calendar sends the user's notes token to the calendar API")
    r = client.call("tools/call", {"name": "forward_to_calendar"})
    print(f"  calendar API that checks audience:   {r['content'][0]['text']}")
    auth2, notes2, _ = setup(check_calendar_audience=False)
    c2 = OAuthMCPClient(notes2.base, log=lambda s: None)
    r = c2.call("tools/call", {"name": "forward_to_calendar"})
    print(f"  calendar API that skips the check:   {r['content'][0]['text']}")
    print("  (the notes server used a token it should never have forwarded; the second API trusted it)")


if __name__ == "__main__":
    main()
