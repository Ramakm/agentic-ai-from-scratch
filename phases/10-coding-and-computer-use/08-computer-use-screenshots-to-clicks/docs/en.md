# Computer Use: Screenshots to Clicks

> A computer-use model looks at a screenshot and answers with pixel coordinates. Between those two lives a controller you write. It downscales screenshots so they fit the model, scales the model's coordinates back up to the real screen, takes a fresh screenshot after every action so the model checks instead of assumes, and stops before clicks that can't be undone. Get the scaling wrong and every click lands somewhere else while the model reports success.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 10 · Browser agents; Phase 2 · Human approval gates; Phase 10 · Anatomy of a coding agent
**Time:** ~60 minutes

## Learning Objectives

- Explain the screenshot → action → screenshot loop and the actions computer-use models emit.
- Implement coordinate scaling between screenshot space and screen space, and show the failure without it.
- Verify each action with a fresh screenshot and flag actions that changed nothing.
- Gate sensitive clicks behind approval, and render real PNG screenshots with the standard library.

## The Problem

Some software has no API and no DOM: a legacy desktop app, a remote desktop, a canvas-based design tool, a PDF form. For those, an agent has to do what people do: look at the screen and click.

Computer-use models can do this. But the first time you wire one up on a high-resolution laptop, something strange happens. The model says "I've turned on dark mode and saved", every step looks plausible in the transcript, and nothing has changed. The model was looking at a 1280×800 screenshot and saying "click (560, 280)". Your code clicked (560, 280) on a 2560×1600 screen, a quarter of the way to the target, on empty background.

## The Concept

**The loop:**

| Step | Who | What |
|------|-----|------|
| 1 | Controller | Capture the screen, downscale it, send it |
| 2 | Model | Choose an action: `left_click [x, y]`, `type "…"`, `key "ctrl+a"`, `scroll`, `screenshot` |
| 3 | Controller | Scale coordinates to the screen, check policy, perform the action |
| 4 | Controller | Capture a new screenshot and send it with the result |
| 5 | Model | Look: did it work? Then the next action |

**Two coordinate spaces:**

| Space | Size here | Who uses it |
|-------|-----------|-------------|
| Screen | 2560 × 1600 (physical pixels on a high-DPI panel) | The OS, the mouse |
| Screenshot | 1280 × 800 | The model |

`screen_x = shot_x × screen_width / shot_width`. Providers advise sending screenshots at a modest resolution, both for cost and because models locate targets more reliably at the sizes they were trained on. You do the scaling, both ways, every time.

**Verification:** every action returns a new screenshot, and the controller compares state before and after. "Nothing on screen changed" goes back to the model explicitly. A missed click that produces no visible change is the most common silent failure.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: a desktop to control

`Desktop.settings_app()` is a settings dialog on a 2560×1600 screen: a title, a "Dark mode" checkbox, a "Display name" field, a "Save" button and a red "Delete account" button marked `sensitive`. `hit(x, y)` finds the widget under a point, which is how the OS decides what you clicked.

### Step 2: screenshots

`render_rgb` rasterises the desktop at the screenshot size and `write_png` encodes it with `zlib` and `struct`. That's a real PNG you can open; the demo writes one per step to a temp folder. For models without vision, `text_screenshot` draws the same screen as a character grid:

```text
                    Account settings........
                    ........................

                      [ ] Dark mode

                      |ada_l..............
                      ....................


                      <Save>..    <Delete account>
```

### Step 3: the controller

```python
def to_screen(self, x, y):
    if not self.scale_coordinates:
        return x, y                                          # the bug
    return round(x * self.desktop.width / self.shot_w), round(y * self.desktop.height / self.shot_h)
```

`act()` scales, checks `sensitive` widgets against `approve()`, performs the action, compares state, logs `[no change]` when nothing changed, and returns the result plus a fresh screenshot.

### Step 4: run it twice

```text
WITHOUT coordinate scaling (screen 2560x1600, screenshot 1280x800):
  left_click [560, 280] -> click at (560, 280) hit empty space  [no change]
  left_click [640, 375] -> click at (640, 375) hit empty space  [no change]
  key 'ctrl+a' -> pressed ctrl+a  [no change]
  key 'BackSpace' -> pressed BackSpace  [no change]
  type 'Ada' -> typed into nothing: no text field has focus  [no change]
  left_click [780, 510] -> click at (780, 510) hit empty space  [no change]
  left_click [520, 510] -> click at (520, 510) hit empty space  [no change]
  model says: Dark mode is on, the display name is Ada, and the settings are saved.
  actually saved: nothing · account deleted: False

WITH coordinate scaling (screen 2560x1600, screenshot 1280x800):
    [approval asked] click 'Delete account' -> no
  left_click [560, 280] -> click at (1120, 560) hit checkbox 'Dark mode'
  left_click [640, 375] -> click at (1280, 750) hit textbox 'Display name'
  key 'ctrl+a' -> selected all text in 'Display name'  [no change]
  key 'BackSpace' -> cleared 'Display name'
  type 'Ada' -> typed 'Ada' into 'Display name'
  left_click [780, 510] -> blocked: clicking 'Delete account' needs the user's approval, which was declined  [no change]
  left_click [520, 510] -> click at (1040, 1020) hit button 'Save'
  model says: Dark mode is on, the display name is Ada, and the settings are saved.
  actually saved: {'dark': True, 'name': 'Ada'} · account deleted: False
```

Same model replies, same final message, opposite outcomes. Without scaling, every action is `[no change]`. A real model would see that in its screenshots and should stop. The scripted one doesn't, which is why the harness must check outcomes and never trust the final message. With scaling, the task completes, and the misclick on "Delete account" (an easy mistake when two buttons sit side by side) is stopped by the approval gate.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Provider / tool | Action space | Notes |
|-----------------|--------------|-------|
| Anthropic computer use tool | `screenshot`, clicks, `type`, `key`, mouse moves, scroll, and more | You run the controller (often in a container with a virtual display) |
| OpenAI computer use (Responses API) | clicks, typing, keypresses, scroll, screenshots | Same pattern: the app executes actions and returns screenshots |
| Browser-only agents (Lesson 7) | DOM refs | Prefer these when a DOM exists |
| Benchmarks | OSWorld, WebArena, and others | Measure task success on real apps (Phase 11 · Lesson 9) |

Run computer-use agents in a virtual machine or container with a virtual display, not on your own desktop with your logged-in accounts.

## Ship It

`outputs/skill-computer-use-controller.md` is a checklist for building a computer-use controller: screenshot size and scaling, action allow-list, verification after each action, sensitive-region gating, and running in an isolated VM.

## Exercises

1. **Easy.** Change the screenshot size to 1024×640. What changes in `to_screen`, and what stays the same in the script? (Hint: the script's coordinates must change too.)
2. **Medium.** Add a `scroll` action and a dialog taller than the screen, so "Save" is only reachable after scrolling.
3. **Medium.** Stop the run automatically after 3 consecutive `[no change]` actions and return "stuck: my actions aren't changing the screen".
4. **Hard.** Give a vision model the PNGs (`AGENT_BASE_URL` pointing at a vision-capable endpoint, sending images as base64). Measure click accuracy with and without scaling on 20 runs.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Computer use | "The agent uses the computer" | A model choosing mouse and keyboard actions from screenshots |
| Screenshot space | "Model coordinates" | Pixel coordinates in the downscaled image the model saw |
| Screen space | "Real coordinates" | Physical pixel coordinates the OS uses for input |
| Hit testing | "What did I click?" | Finding the widget under a point |
| Verification screenshot | "Check your work" | A fresh capture after each action, compared with the previous state |
| Sensitive region | "Danger zone" | A widget whose click needs approval: delete, send, pay |

## Further Reading

- [Anthropic, Computer use tool](https://docs.claude.com/en/docs/agents-and-tools/tool-use/computer-use-tool)
- [Anthropic computer use reference implementation](https://github.com/anthropics/claude-quickstarts/tree/main/computer-use-demo)
- [OpenAI, Computer use guide](https://platform.openai.com/docs/guides/tools-computer-use)
- [Xie et al., OSWorld: benchmarking multimodal agents for open-ended tasks in real computer environments (2024)](https://arxiv.org/abs/2404.07972)
- [PNG specification (W3C)](https://www.w3.org/TR/png/)
