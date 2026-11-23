---
name: computer-use-controller
description: >
  Build or review the controller between a computer-use model and a real screen:
  screenshot sizing and coordinate scaling, allowed actions, verification after every
  action, approval for sensitive regions, and isolation. Use when wiring up Anthropic
  or OpenAI computer use, or when a computer-use agent "succeeds" without changing anything.
---

# Computer-use controller checklist

## Screenshots and coordinates
- [ ] Screenshot size chosen deliberately (follow the provider's recommended resolution)
- [ ] `to_screen(x, y)` scales by screen ÷ screenshot on both axes; tested with a known widget centre
- [ ] High-DPI: you know whether your capture and input APIs use physical or logical pixels
- [ ] Coordinates outside the screenshot are rejected with a message

## Actions
- [ ] Allow-list of actions (click, type, key, scroll, screenshot…); unknown actions rejected
- [ ] Dangerous key combos blocked or gated (closing windows, system shortcuts)

## Verification
- [ ] Every action returns a fresh screenshot
- [ ] State or image diff before vs after; "Nothing on screen changed" reported explicitly
- [ ] N consecutive no-change actions → stop as stuck
- [ ] Task success checked from the app's state, not the model's final message

## Safety
- [ ] Sensitive regions or windows (delete, send, pay, settings) require approval
- [ ] Runs in a VM or container with a virtual display; no personal accounts logged in
- [ ] Every action logged with coordinates, target and screenshot reference
