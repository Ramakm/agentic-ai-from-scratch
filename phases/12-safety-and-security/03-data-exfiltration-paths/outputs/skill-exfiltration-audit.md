---
name: exfiltration-audit
description: >
  Audit how data can leave an LLM agent: list every egress channel (tools, rendered
  markdown, links, URLs, innocuous fields, allowed multi-tenant hosts), check each against
  destination allow-lists, content matching and canary tokens, and recommend fixes.
  Use when an agent can read private data, or after adding a tool that talks to the network.
---

# Exfiltration audit

## 1. Channels
For each, answer yes/no and where it's implemented:
- Does the UI render markdown images? From which hosts? (check CSP `img-src`)
- Does the UI render links? Are they shown with the full URL?
- Which tools take a URL, host, email address, channel or repo as an argument?
- Which tools write free text somewhere others can read (titles, comments, file names, commits)?
- Which allowed hosts let anyone post (forms, gists, public repos, webhooks, pastebins)?

## 2. Detectors

| Detector | Present? | Where enforced (code, proxy, CSP)? |
|----------|----------|------------------------------------|
| destination allow-list for tools | | |
| image/link allow-list for output | | |
| content matching for secrets seen this session, after decoding | | |
| canary tokens in private data | | |

Allow-lists must match hosts exactly or as real parent domains, never by substring.

## 3. Attempts table
Write at least: markdown image, link, encoded URL, chunked subdomain, innocuous field,
allowed multi-tenant host, and one transformation you don't decode. Add four legitimate
egress cases. Report which detector caught each, and the false positives.

## 4. Recommend
Detection gaps are expected. The fix list should start with removing secrets or untrusted
content from the session (split sessions, brokered credentials), then narrowing allow-lists
from hosts to exact URLs, then detection.
