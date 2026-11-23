"""Computer use: the model sees a screenshot and answers with pixel coordinates. This file
simulates a desktop so you can see the parts that go wrong: coordinate scaling between the
screenshot and the real screen, hit-testing, verifying every action with a new screenshot,
and pausing before consequential clicks.

    python3 main.py                  # offline, scripted model; writes PNG screenshots to a temp dir
    AGENT_BASE_URL=... AGENT_MODEL=... python3 main.py   # text-only models get a character-grid "screenshot"

Standard library only.
"""
from __future__ import annotations

import copy
import json
import os
import struct
import tempfile
import urllib.request
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LLM = Callable[[list, list], dict]

# ---------------------------------------------------------------- a fake desktop

@dataclass
class Widget:
    id: str
    kind: str                 # button | checkbox | textbox | label
    label: str
    x: int
    y: int
    w: int
    h: int
    value: str = ""
    checked: bool = False
    sensitive: bool = False   # clicking it has consequences outside the app

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


@dataclass
class Desktop:
    """Physical screen: 2560x1600 like a high-DPI laptop panel."""
    width: int = 2560
    height: int = 1600
    widgets: list[Widget] = field(default_factory=list)
    focus: str | None = None
    saved: dict = field(default_factory=dict)
    sent: bool = False

    @classmethod
    def settings_app(cls) -> "Desktop":
        return cls(widgets=[
            Widget("title", "label", "Account settings", 800, 300, 960, 120),
            Widget("dark", "checkbox", "Dark mode", 880, 520, 480, 80),
            Widget("name", "textbox", "Display name", 880, 700, 800, 100, value="ada_l"),
            Widget("save", "button", "Save", 880, 960, 320, 120),
            Widget("delete", "button", "Delete account", 1360, 960, 400, 120, sensitive=True),
        ])

    def hit(self, x: int, y: int) -> Widget | None:
        return next((w for w in self.widgets if w.contains(x, y)), None)

    def click(self, x: int, y: int) -> str:
        w = self.hit(x, y)
        if not w:
            self.focus = None
            return f"click at ({x}, {y}) hit empty space"
        if w.kind == "checkbox":
            w.checked = not w.checked
        elif w.kind == "textbox":
            self.focus = w.id
        elif w.id == "save":
            self.saved = {x.id: (x.checked if x.kind == "checkbox" else x.value) for x in self.widgets
                          if x.kind in ("checkbox", "textbox")}
        elif w.id == "delete":
            self.sent = True
        return f"click at ({x}, {y}) hit {w.kind} '{w.label}'"

    def type(self, text: str) -> str:
        w = next((x for x in self.widgets if x.id == self.focus), None)
        if not w:
            return "typed into nothing: no text field has focus"
        w.value = text
        return f"typed {text!r} into '{w.label}'"

    def key(self, combo: str) -> str:
        w = next((x for x in self.widgets if x.id == self.focus), None)
        if combo in ("ctrl+a", "cmd+a") and w:
            return f"selected all text in '{w.label}'"
        if combo == "BackSpace" and w:
            w.value = ""
            return f"cleared '{w.label}'"
        return f"pressed {combo}"

    def state(self) -> tuple:
        return tuple((w.id, w.value, w.checked) for w in self.widgets) + (self.focus, tuple(sorted(self.saved.items())))

# ---------------------------------------------------------------- screenshots

def render_rgb(d: Desktop, width: int, height: int) -> bytes:
    """Rasterise the desktop at the screenshot size: background, then each widget's rectangle, scaled down."""
    colours = {"label": (230, 230, 235), "checkbox": (180, 200, 255), "textbox": (255, 255, 255),
               "button": (60, 120, 220)}
    px = bytearray(bytes((40, 44, 52)) * (width * height))
    sx, sy = width / d.width, height / d.height
    for w in d.widgets:
        c = (210, 60, 60) if w.id == "delete" else (60, 180, 90) if w.kind == "checkbox" and w.checked \
            else colours.get(w.kind, (200, 200, 200))
        x0, x1 = int(w.x * sx), min(width, int((w.x + w.w) * sx))
        line = bytes(c) * (x1 - x0)
        for y in range(int(w.y * sy), min(height, int((w.y + w.h) * sy))):
            px[(y * width + x0) * 3:(y * width + x1) * 3] = line
    return bytes(px)


def write_png(path: Path, rgb: bytes, width: int, height: int) -> None:
    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def text_screenshot(d: Desktop, cols: int = 64, rows: int = 20) -> str:
    """For text-only models: a character grid where each cell is (width/cols) x (height/rows) screenshot pixels."""
    grid = [[" "] * cols for _ in range(rows)]
    for w in d.widgets:
        c0, r0 = int(w.x / d.width * cols), int(w.y / d.height * rows)
        c1, r1 = max(c0 + 1, int((w.x + w.w) / d.width * cols)), max(r0 + 1, int((w.y + w.h) / d.height * rows))
        mark = {"checkbox": "[x] " if w.checked else "[ ] ", "textbox": "|", "button": "<"}.get(w.kind, "")
        text = (mark + (w.value if w.kind == "textbox" else w.label) + (">" if w.kind == "button" else ""))
        for r in range(r0, min(r1, rows)):
            for c in range(c0, min(c1, cols)):
                grid[r][c] = "."
        for i, ch in enumerate(text[: cols - c0]):            # labels may run past the box, like real text
            grid[r0][c0 + i] = ch
    return "\n".join("".join(r) for r in grid)

# ---------------------------------------------------------------- the controller

@dataclass
class Controller:
    """Sits between the model and the desktop. The model works in SCREENSHOT pixels; the desktop in SCREEN pixels."""
    desktop: Desktop
    shot_w: int = 1280
    shot_h: int = 800
    scale_coordinates: bool = True
    approve: Callable[[str], bool] = lambda what: False
    png_dir: Path | None = None
    log: list[str] = field(default_factory=list)
    shots: int = 0

    def to_screen(self, x: int, y: int) -> tuple[int, int]:
        if not self.scale_coordinates:
            return x, y                                          # the bug: screenshot pixels used as screen pixels
        return round(x * self.desktop.width / self.shot_w), round(y * self.desktop.height / self.shot_h)

    def screenshot(self) -> str:
        self.shots += 1
        if self.png_dir:
            write_png(self.png_dir / f"shot_{self.shots:02d}.png", render_rgb(self.desktop, self.shot_w, self.shot_h),
                      self.shot_w, self.shot_h)
        return f"[screenshot {self.shot_w}x{self.shot_h}]\n" + text_screenshot(self.desktop)

    def act(self, action: str, **kw) -> str:
        before = self.desktop.state()
        if action == "screenshot":
            return self.screenshot()
        if action == "left_click":
            x, y = self.to_screen(*kw["coordinate"])
            target = self.desktop.hit(x, y)
            if target and target.sensitive and not self.approve(f"click '{target.label}'"):
                result = f"blocked: clicking '{target.label}' needs the user's approval, which was declined"
            else:
                result = self.desktop.click(x, y)
        elif action == "type":
            result = self.desktop.type(kw["text"])
        elif action == "key":
            result = self.desktop.key(kw["text"])
        else:
            return f"error: unknown action {action!r}"
        changed = self.desktop.state() != before
        self.log.append(f"{action}{' ' + str(kw['coordinate']) if 'coordinate' in kw else ''}"
                        f"{' ' + repr(kw['text']) if 'text' in kw else ''} -> {result}{'' if changed else '  [no change]'}")
        # every action returns a fresh screenshot: the model must look, not assume
        return f"{result}\n{'' if changed else 'Nothing on screen changed. '}" + self.screenshot()


SCHEMAS = [{"type": "function", "function": {"name": "computer", "description":
            "Control the computer. Coordinates are in screenshot pixels (1280x800).", "parameters": {
            "type": "object", "properties": {"action": {"type": "string", "enum": ["screenshot", "left_click", "type", "key"]},
                                             "coordinate": {"type": "array", "items": {"type": "integer"}},
                                             "text": {"type": "string"}}, "required": ["action"]}}}]


def run(task: str, llm: LLM, ctl: Controller, max_steps: int = 15) -> str:
    messages = [{"role": "system", "content": "You control a computer through screenshots. After each action, "
                 "check the new screenshot to confirm it worked before moving on."},
                {"role": "user", "content": task}]
    for _ in range(max_steps):
        reply = llm(messages, SCHEMAS)
        messages.append(reply)
        if not reply.get("tool_calls"):
            return reply.get("content") or ""
        for c in reply["tool_calls"]:
            args = json.loads(c["function"].get("arguments") or "{}")
            out = ctl.act(args.pop("action", ""), **args)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    return "(step budget spent)"

# ---------------------------------------------------------------- scripted model

def _act(i: str, **args) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": i, "type": "function", "function": {"name": "computer", "arguments": json.dumps(args)}}]}


# Coordinates a model would read off a 1280x800 screenshot (widget centres at half the screen's pixels).
DEMO_SCRIPT = [
    _act("1", action="screenshot"),
    _act("2", action="left_click", coordinate=[560, 280]),        # Dark mode checkbox
    _act("3", action="left_click", coordinate=[640, 375]),        # Display name field
    _act("4", action="key", text="ctrl+a"),
    _act("5", action="key", text="BackSpace"),
    _act("6", action="type", text="Ada"),
    _act("7", action="left_click", coordinate=[780, 510]),        # Delete account: a mistake
    _act("8", action="left_click", coordinate=[520, 510]),        # Save
    {"role": "assistant", "content": "Dark mode is on, the display name is Ada, and the settings are saved."},
]


def scripted_llm(script: list[dict]) -> LLM:
    replies = iter(copy.deepcopy(script))
    return lambda messages, schemas: next(replies)


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list, schemas: list) -> dict:
        body = json.dumps({"model": model, "messages": messages, "tools": schemas}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
    return call


TASK = "Turn on dark mode, change the display name to Ada, and save."

if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    make = (lambda: openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "qwen2.5"), os.environ.get("AGENT_API_KEY", ""))) \
        if base else (lambda: scripted_llm(DEMO_SCRIPT))
    print("what a text-only model sees (64x20 grid standing in for a 1280x800 screenshot):\n")
    print(text_screenshot(Desktop.settings_app()))
    for scaled in (False, True):
        d = Desktop.settings_app()
        pngs = Path(tempfile.mkdtemp(prefix="screens-"))
        ctl = Controller(d, scale_coordinates=scaled, png_dir=pngs,
                         approve=lambda what: print(f"    [approval asked] {what} -> no") or False)
        print(f"\n{'WITH' if scaled else 'WITHOUT'} coordinate scaling (screen {d.width}x{d.height}, screenshot 1280x800):")
        answer = run(TASK, make(), ctl)
        for line in ctl.log:
            print(f"  {line}")
        print(f"  model says: {answer}")
        print(f"  actually saved: {d.saved or 'nothing'} · account deleted: {d.sent}")
        print(f"  {ctl.shots} screenshots written as PNG to a temp folder")
