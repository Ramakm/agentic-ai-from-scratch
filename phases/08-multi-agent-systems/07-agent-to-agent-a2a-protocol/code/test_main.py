import time
import unittest

from main import TERMINAL, A2AClient, A2AError, HotelAgent, serve, user_message


class A2ATests(unittest.TestCase):
    def setUp(self):
        self.agent = HotelAgent(work_seconds=0.15)
        self.srv, base = serve(self.agent)
        self.addCleanup(self.srv.shutdown)
        self.c = A2AClient(base)

    def send(self, text="", **kw):
        return self.c.call("SendMessage", {"message": user_message(text, **kw)})["task"]

    def test_card(self):
        iface = self.c.card["supportedInterfaces"][0]
        self.assertEqual((iface["protocolBinding"], iface["protocolVersion"]), ("JSONRPC", "1.0"))
        self.assertTrue(self.c.url.endswith("/a2a"))
        self.assertEqual(self.c.card["skills"][0]["id"], "book-hotel")

    def test_input_required_then_complete_same_task(self):
        t = self.send("Book a hotel in Lisbon")
        self.assertEqual(t["status"]["state"], "TASK_STATE_INPUT_REQUIRED")
        self.assertEqual(t["status"]["message"]["role"], "ROLE_AGENT")
        t2 = self.send(data={"max_per_night": 100}, task=t)
        self.assertEqual((t2["id"], t2["status"]["state"]), (t["id"], "TASK_STATE_COMPLETED"))
        data = next(p["data"] for p in t2["artifacts"][0]["parts"] if "data" in p)
        self.assertEqual(data["hotel"], "Alfama Rooms")

    def test_follow_up_on_terminal_task_fails(self):
        t = self.send("Lisbon under 150")
        with self.assertRaises(A2AError) as e:
            self.send("again", task=t)
        self.assertEqual(e.exception.code, -32004)

    def test_poll_and_cancel(self):
        t = self.c.call("SendMessage", {"message": user_message("Lisbon under 150"),
                                        "configuration": {"returnImmediately": True}})["task"]
        self.assertEqual(t["status"]["state"], "TASK_STATE_WORKING")
        self.c.call("CancelTask", {"id": t["id"]})
        time.sleep(0.3)
        self.assertEqual(self.c.call("GetTask", {"id": t["id"]})["status"]["state"], "TASK_STATE_CANCELED")

    def test_streaming_events(self):
        kinds = [next(iter(e)) for e in self.c.stream({"message": user_message("Lisbon under 200")})]
        self.assertEqual(kinds, ["statusUpdate", "artifactUpdate", "statusUpdate"])

    def test_errors_and_rejection(self):
        with self.assertRaises(A2AError) as e:
            self.c.call("GetTask", {"id": "nope"})
        self.assertEqual((e.exception.code, e.exception.reason), (-32001, "TASK_NOT_FOUND"))
        done = self.send("Lisbon under 150")
        with self.assertRaises(A2AError) as e:
            self.c.call("CancelTask", {"id": done["id"]})
        self.assertEqual(e.exception.code, -32002)
        self.assertEqual(self.send("Atlantis under 90")["status"]["state"], "TASK_STATE_REJECTED")
        self.assertIn("TASK_STATE_REJECTED", TERMINAL)

    def test_no_hotel_in_budget_fails(self):
        self.assertEqual(self.send("Lisbon under 50")["status"]["state"], "TASK_STATE_FAILED")


if __name__ == "__main__":
    unittest.main()
