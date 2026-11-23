---
name: mcp-remote-auth-review
description: >
  Review authorization for a remote (HTTP) MCP server and its clients against MCP's OAuth 2.1
  profile: Protected Resource Metadata and 401/403 WWW-Authenticate challenges, authorization server
  discovery, PKCE S256, the resource parameter and audience validation, state and iss checks,
  client registration (Client ID Metadata Documents, pre-registration, deprecated DCR), scope design
  and step-up, token handling, and the no-token-passthrough rule. Use when exposing an MCP server
  beyond localhost or when a client fails to authenticate.
---

# MCP Remote Auth Review

## 1. Server discovery

- Serves `/.well-known/oauth-protected-resource` with `resource` (canonical URI, no trailing
  slash, no fragment) and `authorization_servers`.
- 401: `WWW-Authenticate: Bearer resource_metadata="...", scope="<minimal>"`.
- 403: `error="insufficient_scope"`, `scope` with everything this operation needs, `resource_metadata`.

## 2. Server token checks (every request)

Authorization header only (never query string). Signature/introspection, `iss`, `exp`, `aud` equals
this server's canonical URI, scope covers the operation (respect scope hierarchy). Failures: 401 invalid
or expired, 403 insufficient scope.

## 3. Never pass tokens through

Downstream calls use a token issued for the downstream API (own client credentials or token
exchange). Reject tokens not issued for this server.

## 4. Client flow

PRM -> AS metadata (RFC 8414, then OIDC) -> require S256 -> record issuer and state -> authorize with
`resource`, minimal `scope`, PKCE -> check `state` and `iss` -> token request with `code_verifier` and
`resource` -> store token keyed by server and issuer.

## 5. Step-up

On 403: union of granted and challenged scopes, re-authorize, retry a bounded number of times.

## 6. Registration

Prefer a Client ID Metadata Document (HTTPS URL as client_id, exact redirect URIs); else
pre-registration; DCR only for legacy authorization servers.

## 7. stdio

No OAuth flow; credentials from the environment, least privilege.

Reference: Agentic AI from Scratch, Phase 7, Lesson 7.
