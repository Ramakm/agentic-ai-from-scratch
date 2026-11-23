import tempfile
import unittest
import zlib
from pathlib import Path

from main import DEMO_SCRIPT, TASK, Controller, Desktop, render_rgb, run, scripted_llm, text_screenshot, write_png


class DesktopTests(unittest.TestCase):
    def test_hit_testing(self):
        d = Desktop.settings_app()
        self.assertEqual(d.hit(*d.widgets[1].center).id, "dark")
        self.assertIsNone(d.hit(10, 10))

    def test_typing_needs_focus(self):
        d = Desktop.settings_app()
        self.assertIn("no text field has focus", d.type("x"))
        d.click(*next(w for w in d.widgets if w.id == "name").center)
        self.assertIn("typed 'x'", d.type("x"))


class ControllerTests(unittest.TestCase):
    def test_coordinate_scaling(self):
        c = Controller(Desktop.settings_app())
        self.assertEqual(c.to_screen(640, 400), (1280, 800))
        self.assertEqual(Controller(Desktop.settings_app(), scale_coordinates=False).to_screen(640, 400), (640, 400))

    def test_without_scaling_every_click_misses_and_is_reported(self):
        d = Desktop.settings_app()
        ctl = Controller(d, scale_coordinates=False)
        answer = run(TASK, scripted_llm(DEMO_SCRIPT), ctl)
        self.assertIn("saved", answer)                       # the model claims success...
        self.assertEqual(d.saved, {})                        # ...but nothing happened
        self.assertTrue(all("[no change]" in line for line in ctl.log))

    def test_with_scaling_the_task_completes(self):
        d = Desktop.settings_app()
        run(TASK, scripted_llm(DEMO_SCRIPT), Controller(d))
        self.assertEqual(d.saved, {"dark": True, "name": "Ada"})

    def test_sensitive_clicks_need_approval(self):
        d = Desktop.settings_app()
        ctl = Controller(d, approve=lambda what: False)
        out = ctl.act("left_click", coordinate=[780, 510])
        self.assertIn("needs the user's approval", out)
        self.assertFalse(d.sent)
        Controller(d, approve=lambda what: True).act("left_click", coordinate=[780, 510])
        self.assertTrue(d.sent)

    def test_every_action_returns_a_fresh_screenshot(self):
        ctl = Controller(Desktop.settings_app())
        out = ctl.act("left_click", coordinate=[560, 280])
        self.assertIn("[screenshot 1280x800]", out)
        self.assertIn("[x] Dark mode", out)
        self.assertIn("Nothing on screen changed", ctl.act("left_click", coordinate=[5, 5]))


class ScreenshotTests(unittest.TestCase):
    def test_png_is_valid(self):
        path = Path(tempfile.mkdtemp()) / "s.png"
        write_png(path, render_rgb(Desktop.settings_app(), 64, 40), 64, 40)
        data = path.read_bytes()
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
        self.assertEqual(len(zlib.decompress(idat)), 40 * (1 + 64 * 3))

    def test_text_screenshot_shows_state(self):
        d = Desktop.settings_app()
        self.assertIn("[ ] Dark mode", text_screenshot(d))
        self.assertIn("|ada_l", text_screenshot(d))


if __name__ == "__main__":
    unittest.main()
