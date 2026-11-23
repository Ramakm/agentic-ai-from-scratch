# Auth for Remote Servers

> A remote MCP server is an OAuth 2.1 resource server. It tells clients where to get a token, accepts only tokens minted for it, asks for more scope when an operation needs it, and never hands a user's token to anyone else. Each of those rules closes a specific attack.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 7 · Lesson 6
**Time:** ~50 minutes

## Learning Objectives

- Implement the discovery chain: 401 with `WWW-Authenticate`, Protected Resource Metadata (RFC 9728), then authorization server metadata (RFC 8414).
- Run the authorization code flow with PKCE (S256), the `resource` parameter (RFC 8707), `state` and `iss` checks, and a Client ID Metadata Document as the client id.
- Validate tokens on the server: signature, issuer, expiry, and audience, with the token only accepted from the `Authorization` header.
- Handle `insufficient_scope` with step-up authorization, and explain why token passthrough is forbidden.

## The Problem

The Lesson 6 server answered anyone who could reach it. That's fine on localhost and wrong for a server holding a user's notes, email or company data. A remote server needs to know who's calling and what they're allowed to do.

Hand-rolled API keys don't fit MCP well. The user adds a server URL to a host they didn't write, and the host has never heard of that server before. Asking users to paste long-lived keys into every tool means keys copied around, never scoped, never rotated. What's needed is a standard way for any client to discover how to get a token for any server, have the user approve exactly what the client may do, and get a short-lived token that's useless anywhere else.

That's OAuth. MCP uses a specific, tightened subset of it for HTTP transports. (For stdio servers, the spec says to take credentials from the environment instead: the server runs as the user, on the user's machine.)

## The Concept

```
 client                       notes MCP server              authorization server
   │  POST /mcp (no token)          │                               │
   │ ─────────────────────────────► │                               │
   │  401 WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource", scope="notes:read"
   │ ◄───────────────────────────── │                               │
   │  GET /.well-known/oauth-protected-resource                     │
   │ ─────────────────────────────► │  {resource, authorization_servers: [AS]}
   │  GET AS/.well-known/oauth-authorization-server ───────────────►│  endpoints, S256, issuer
   │  (browser) /authorize?client_id=<metadata URL>&code_challenge=…&resource=<server>&scope=…&state=…
   │ ──────────────────────────────────────────────────────────────►│  user consents
   │  redirect ?code=…&state=…&iss=AS ◄─────────────────────────────│
   │  POST /token code + code_verifier + resource ─────────────────►│  {access_token, aud=server, scope}
   │  POST /mcp  Authorization: Bearer … ►│ checks sig, iss, exp, aud, scope
```

| Mechanism | Stops |
|-----------|-------|
| Protected Resource Metadata | Clients needing per-server configuration to find the authorization server |
| PKCE (S256) | A stolen authorization code being redeemed by someone without the verifier |
| `resource` parameter + audience check | A token for server A being replayed at server B |
| `state` | Cross-site request forgery on the redirect |
| `iss` check (RFC 9207) | Mix-up attacks: a code from one authorization server being sent to another's token endpoint |
| Single-use, short-lived codes | Replay of an intercepted code |
| Tokens only in the `Authorization` header | Tokens leaking through URLs, logs and Referer headers |
| `insufficient_scope` + step-up | Over-broad initial grants: start small, add scope when an operation needs it |
| No token passthrough | A server becoming a confused deputy with the user's credentials |

**Client registration.** The authorization server needs to know the client. In order of preference: a **Client ID Metadata Document** (the `client_id` is an HTTPS URL; the authorization server fetches a JSON document there listing the client's name and redirect URIs), pre-registration, or Dynamic Client Registration (now deprecated in MCP).

**Token passthrough.** If the notes server needs to call a calendar API, it must get its own token for that API. Forwarding the user's notes token breaks audit trails, bypasses the calendar API's controls if it doesn't check audience, and lets anyone who can reach the notes server act with the user's calendar rights. The spec says it plainly: servers must not accept or transit other tokens.

## Build It

```bash
cd code
python3 main.py
```

Three servers start on random localhost ports: an authorization server, the notes MCP server, and a calendar API. In the output their URLs are shown as `<auth-server>`, `<notes-mcp>` and `<calendar-api>`. The user's consent screen is simulated (approve everything by default), and fetching the client's metadata document is a dictionary lookup standing in for an HTTPS fetch.

### Step 1: the server says where to go

```python
def challenge(self, h, status, scope, error=None):
    parts = [f'error="{error}"'] if error else []
    parts += [f'resource_metadata="{self.base}/.well-known/oauth-protected-resource"', f'scope="{scope}"']
    h.reply(status, {...}, {"WWW-Authenticate": "Bearer " + ", ".join(parts)})
```

The metadata document names the server's canonical URI and its authorization servers:

```python
{"resource": self.resource, "authorization_servers": [self.auth.base],
 "scopes_supported": ["notes:read"], "bearer_methods_supported": ["header"]}
```

### Step 2: the client follows the chain

```text
First contact: no token
  tools/call -> 401 scope="notes:read"
    protected resource metadata: resource=<notes-mcp> authorization_servers=[<auth-server>]
    authorization server metadata from /.well-known/oauth-authorization-server
    authorize: scope="notes:read" resource=<notes-mcp> PKCE S256
    token issued: scope="notes:read" expires_in=600
  retry with token -> Q3 planning: book the offsite
```

The client asks for the scope from the challenge, not everything the server supports. It tries RFC 8414 metadata first and OpenID Connect discovery second, and refuses to continue if the authorization server doesn't support S256. Before redirecting, it records the issuer and the `state`; when the redirect comes back, both must match.

```python
verifier, challenge = pkce_pair()          # verifier stays here; challenge = SHA-256(verifier)
...
"code_challenge": challenge, "code_challenge_method": "S256", "resource": prm["resource"]
...
if cb.get("iss") != expected_issuer:
    raise RuntimeError("authorization response iss doesn't match the expected issuer (mix-up?)")
```

### Step 3: step-up

```text
Step-up: writing needs a scope we weren't given
  tools/call -> 403 insufficient_scope scope="notes:write"
    protected resource metadata: resource=<notes-mcp> authorization_servers=[<auth-server>]
    authorization server metadata from /.well-known/oauth-authorization-server
    authorize: scope="notes:read notes:write" resource=<notes-mcp> PKCE S256
    token issued: scope="notes:read notes:write" expires_in=600
  retry with token -> added note 2
  granted now: ['notes:read', 'notes:write']
```

The new request is the **union** of what the client had and what the challenge asked for; otherwise gaining `notes:write` would lose `notes:read`. The client retries a bounded number of times, so a scope the user keeps declining ends in a clear error instead of a loop.

### Step 4: what the server rejects

```python
if (claims is None or claims["iss"] != self.auth.base or claims["exp"] < time.time()
        or claims["aud"] != self.resource):
    return self.challenge(h, 401, "notes:read", "invalid_token")
```

```text
What the MCP server rejects (status, error)
  valid token                                          200
  no token                                             401
  token sent in the query string                       401
  token minted for the calendar API (wrong audience)   401 invalid_token
  expired token                                        401 invalid_token
  scope edited after signing                           401 invalid_token
  token from another issuer                            401 invalid_token
```

The tokens here are signed JSON, a stand-in for JWTs. A real server validates JWTs with the authorization server's published keys, or asks the authorization server about opaque tokens (token introspection). The checks are the same.

### Step 5: what the authorization server rejects

```text
What the authorization server rejects
  stolen code, attacker has no PKCE verifier           400 invalid_grant: PKCE verification failed
  code redeemed for a different resource               400 invalid_target: resource differs from authorization
  code used a second time                              400 invalid_grant: unknown, used or expired code
  redirect_uri not in the client metadata document     400 invalid_request
```

### Step 6: token passthrough

`forward_to_calendar` sends the user's notes token on to the calendar API:

```text
Token passthrough: forward_to_calendar sends the user's notes token to the calendar API
  calendar API that checks audience:   calendar refused: 401
  calendar API that skips the check:   calendar said: {"events": ["Mon 10:00 board meeting"]}
  (the notes server used a token it should never have forwarded; the second API trusted it)
```

Audience validation at the calendar API saved the first case. You can't count on every downstream API doing that, so the rule is on the MCP server: don't forward. To call the calendar, the notes server gets a token for the calendar (its own client credentials, or a token exchange on the user's behalf) with the calendar as the audience.

### Run the tests

```bash
python3 -m unittest -v
```

The tests also cover a mix-up attack (metadata issuer differs from the `iss` in the redirect), a user declining consent, and the retry limit when a user never grants a scope.

## Use It

| Piece | In production |
|-------|---------------|
| Authorization server | Your identity provider (Okta, Auth0, Entra ID, Keycloak, Cognito, others) or a managed MCP auth service |
| Token validation | A JWT library with the issuer's JWKS, or token introspection |
| MCP SDK auth helpers | Serve Protected Resource Metadata, build the 401/403 challenges, verify tokens |
| Host clients | Open the user's browser for consent, store tokens per server and issuer, refresh them |
| API gateways | Can validate tokens before traffic reaches the MCP server |

## Ship It

`outputs/skill-mcp-remote-auth-review.md` is a skill for reviewing auth on a remote MCP server and its clients: discovery documents, challenge headers, PKCE, resource parameter and audience checks, scope design and step-up, registration method, token storage, and the token-passthrough rule.

## Exercises

1. **Easy.** Remove the audience check from the notes server and re-run "What the MCP server rejects". Which row changes?
2. **Medium.** Add refresh tokens: the token endpoint returns one with the access token, and the client uses it when a call gets 401 `invalid_token` because the access token expired, instead of a full re-authorization.
3. **Medium.** Fix `forward_to_calendar` properly: the notes server registers as its own client and gets a calendar-audience token from the authorization server. What scopes should it ask for?
4. **Hard.** Make scopes hierarchical (`notes:admin` implies `notes:write` implies `notes:read`). Update the server's scope check and the client's union logic. What does the spec ask servers to do here?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Resource server | "The API" | The MCP server: accepts and validates access tokens |
| Protected Resource Metadata | "The well-known doc" | RFC 9728 JSON naming the server's canonical URI and authorization servers |
| PKCE | "Pixie" | Proof Key for Code Exchange: the client proves it started the flow by revealing a verifier whose hash it sent first |
| Resource indicator | "Audience" | RFC 8707 `resource` parameter naming the server the token is for; becomes the token's `aud` |
| Step-up authorization | "Ask for more scope" | Re-authorizing with the union of granted and challenged scopes after a 403 `insufficient_scope` |
| Token passthrough | "Forwarding the token" | A server passing a client's token to another API; forbidden in MCP |
| Client ID Metadata Document | "CIMD" | A client id that's an HTTPS URL pointing to the client's metadata JSON |

## Further Reading

- [MCP specification 2026-07-28: Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [RFC 9728: OAuth 2.0 Protected Resource Metadata](https://datatracker.ietf.org/doc/html/rfc9728)
- [RFC 8707: Resource Indicators for OAuth 2.0](https://www.rfc-editor.org/rfc/rfc8707.html)
- [RFC 7636: Proof Key for Code Exchange (PKCE)](https://datatracker.ietf.org/doc/html/rfc7636)
- [RFC 9207: OAuth 2.0 Authorization Server Issuer Identification](https://datatracker.ietf.org/doc/html/rfc9207)
- [OAuth 2.1 draft](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-13)
