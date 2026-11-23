"""Message passing with mailboxes: agents as actors that share nothing, own a queue, and handle one
message at a time. Request/reply with correlation ids, at-least-once delivery with idempotent
handlers, bounded mailboxes for backpressure, and a dead-letter queue for poison messages.

    python3 main.py

Agents here are plain handlers (no model) so the run is deterministic; in a real system a handler
would call a model or tools. The unreliable network is simulated: whether a delivery is dropped or
duplicated is decided by a hash of the message id, so it's the same on every run.
"""
from __future__ import annotations

import hashlib
import queue
import threading
import time
import itertools
from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------------
# Envelopes, actors and the bus
# --------------------------------------------------------------------------------------------

_ids = itertools.count(1)  # real systems use UUIDs; counters keep this lesson's run reproducible


@dataclass
class Envelope:
    kind: str
    body: dict
    sender: str
    recipient: str
    id: str = field(default_factory=lambda: f"m{next(_ids)}")
    correlation_id: str | None = None   # for replies: the id of the request
    attempt: int = 1


class Bus:
    def __init__(self, drop_rate: float = 0.0, dup_rate: float = 0.0):
        self.actors: dict[str, "Actor"] = {}
        self.dead_letters: list[tuple[Envelope, str]] = []
        self.drop_rate, self.dup_rate = drop_rate, dup_rate
        self.stats = {"sent": 0, "dropped": 0, "duplicated": 0, "rejected_full": 0}
        self.lock = threading.Lock()

    def _roll(self, env: Envelope, salt: str) -> float:
        h = hashlib.sha256(f"{env.id}:{env.attempt}:{salt}".encode()).digest()
        return int.from_bytes(h[:4], "big") / 2**32

    def send(self, env: Envelope, timeout: float = 0.5) -> bool:
        target = self.actors.get(env.recipient)
        with self.lock:
            self.stats["sent"] += 1
        if target is None:
            self.dead_letters.append((env, "no such recipient"))
            return False
        if self._roll(env, "drop") < self.drop_rate:
            with self.lock:
                self.stats["dropped"] += 1
            return True  # the sender can't tell: that's what makes networks hard
        copies = 2 if self._roll(env, "dup") < self.dup_rate else 1
        for _ in range(copies):
            try:
                target.mailbox.put(env, timeout=timeout)
            except queue.Full:
                with self.lock:
                    self.stats["rejected_full"] += 1
                return False
        if copies == 2:
            with self.lock:
                self.stats["duplicated"] += 1
        return True


class Actor:
    """Owns its state. Nobody else touches it; the only way in is the mailbox."""

    def __init__(self, name: str, bus: Bus, capacity: int = 100, max_attempts: int = 3):
        self.name, self.bus = name, bus
        self.mailbox: queue.Queue = queue.Queue(maxsize=capacity)
        self.max_attempts = max_attempts
        self.failures: dict[str, int] = {}
        self.peak_depth = 0
        bus.actors[name] = self
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        while True:
            env = self.mailbox.get()
            if env is None:
                return
            self.peak_depth = max(self.peak_depth, self.mailbox.qsize() + 1)
            try:
                self.handle(env)
            except Exception as e:  # a handler failure: retry by re-queueing, then dead-letter
                n = self.failures[env.id] = self.failures.get(env.id, 0) + 1
                if n >= self.max_attempts:
                    self.bus.dead_letters.append((env, f"{type(e).__name__}: {e} after {n} attempts"))
                else:
                    self.mailbox.put(env)
            finally:
                self.mailbox.task_done()

    def handle(self, env: Envelope) -> None:
        raise NotImplementedError

    def reply(self, request: Envelope, kind: str, body: dict) -> None:
        self.bus.send(Envelope(kind, body, self.name, request.sender, id=f"{request.id}.r{request.attempt}",
                               correlation_id=request.id))

    def stop(self) -> None:
        self.mailbox.put(None)
        self.thread.join(timeout=2)


class Requester(Actor):
    """Sends requests and waits for replies by correlation id; resends on timeout (at-least-once)."""

    def __init__(self, name: str, bus: Bus, **kw):
        self.waiting: dict[str, queue.Queue] = {}
        super().__init__(name, bus, **kw)

    def handle(self, env: Envelope) -> None:
        box = self.waiting.get(env.correlation_id)
        if box:
            box.put(env)
        # replies nobody waits for any more (duplicates, late ones) are ignored

    def ask(self, recipient: str, kind: str, body: dict, timeout: float = 0.1, retries: int = 4) -> Envelope | None:
        self.asked = getattr(self, "asked", 0) + 1
        env = Envelope(kind, body, self.name, recipient, id=f"{self.name}-{self.asked}")
        box = self.waiting[env.id] = queue.Queue()
        try:
            for attempt in range(1, retries + 2):
                env.attempt = attempt
                self.bus.send(env)          # same id every time: receivers can recognise a resend
                try:
                    return box.get(timeout=timeout)
                except queue.Empty:
                    continue
            return None
        finally:
            self.waiting.pop(env.id, None)


# --------------------------------------------------------------------------------------------
# Agents for the demo
# --------------------------------------------------------------------------------------------


class Billing(Actor):
    """Charges per research call. Must not charge twice for the same request."""

    def __init__(self, name, bus, dedupe: bool, **kw):
        self.dedupe = dedupe
        self.seen: set[str] = set()
        self.charges: list[str] = []
        super().__init__(name, bus, **kw)

    def handle(self, env: Envelope) -> None:
        if self.dedupe and env.id in self.seen:
            self.reply(env, "charged", {"status": "already charged"})
            return
        self.seen.add(env.id)
        self.charges.append(env.body["job"])
        self.reply(env, "charged", {"status": "ok"})


class Summariser(Actor):
    def __init__(self, name, bus, delay: float = 0.0, **kw):
        self.delay = delay
        self.done = 0
        super().__init__(name, bus, **kw)

    def handle(self, env: Envelope) -> None:
        if env.body.get("text") == "<binary garbage>":
            raise ValueError("cannot decode input")
        time.sleep(self.delay)
        self.done += 1
        if env.sender in self.bus.actors and isinstance(self.bus.actors[env.sender], Requester):
            self.reply(env, "summary", {"summary": env.body["text"][:20]})


def run_billing(dedupe: bool, jobs: int = 40) -> dict:
    bus = Bus(drop_rate=0.15, dup_rate=0.10)
    billing = Billing("billing", bus, dedupe=dedupe)
    planner = Requester("planner", bus)
    answered = sum(planner.ask("billing", "charge", {"job": f"job-{i}"}) is not None for i in range(jobs))
    time.sleep(0.1)
    billing.stop()
    planner.stop()
    return {"answered": answered, "charges": len(billing.charges), "unique": len(set(billing.charges)),
            **bus.stats}


def run_backpressure(capacity: int, wait_when_full: bool, messages: int = 30) -> dict:
    """The consumer is busy (paused) while the producer sends, as when a burst arrives."""
    bus = Bus()
    gate = threading.Event()
    slow = Summariser("summariser", bus, capacity=capacity)
    slow.mailbox.put(Envelope("pause", {"text": "warm-up"}, "crawler", "summariser"))
    original = slow.handle
    slow.handle = lambda env: gate.wait() if env.kind == "pause" else original(env)
    time.sleep(0.05)  # let the consumer pick up the pause message
    accepted = 0
    producer_waited = False
    for i in range(messages):
        env = Envelope("summarise", {"text": f"doc {i}"}, "crawler", "summariser")
        if wait_when_full:
            if slow.mailbox.full():
                producer_waited = True
                gate.set()  # in real life the consumer catches up; here we let it go
            slow.mailbox.put(env)
            accepted += 1
        else:
            try:
                slow.mailbox.put_nowait(env)
                accepted += 1
            except queue.Full:
                bus.stats["rejected_full"] += 1
    gate.set()
    slow.mailbox.join()
    slow.stop()
    return {"accepted": accepted, "rejected": bus.stats["rejected_full"], "done": slow.done,
            "peak": slow.peak_depth, "waited": producer_waited}


def main() -> None:
    print("1. Request/reply with correlation ids over a lossy bus (15% dropped, 10% duplicated)")
    for dedupe in (False, True):
        r = run_billing(dedupe)
        label = "billing dedupes by message id" if dedupe else "billing without dedupe       "
        print(f"  {label}: 40 jobs, {r['answered']} answered, {r['charges']} charges for {r['unique']} jobs "
              f"(sends {r['sent']}, dropped {r['dropped']}, duplicated {r['duplicated']})")

    print("\n2. Backpressure: a burst of 30 messages while the consumer is busy")
    for cap, wait, label in [(1000, False, "unbounded-ish mailbox       "), (5, False, "bounded (5), drop when full "),
                             (5, True, "bounded (5), producer waits ")]:
        r = run_backpressure(cap, wait)
        print(f"  {label}: accepted {r['accepted']:>2}, rejected {r['rejected']:>2}, processed {r['done']:>2}, "
              f"peak mailbox depth {r['peak']:>2}{', producer had to wait' if r['waited'] else ''}")

    print("\n3. Poison message and unknown recipient")
    bus = Bus()
    s = Summariser("summariser", bus)
    bus.send(Envelope("summarise", {"text": "<binary garbage>"}, "crawler", "summariser"))
    bus.send(Envelope("summarise", {"text": "a normal document"}, "crawler", "summariser"))
    bus.send(Envelope("summarise", {"text": "lost"}, "crawler", "translator"))
    time.sleep(0.2)
    s.stop()
    print(f"  summariser processed {s.done} message(s)")
    for env, why in sorted(bus.dead_letters, key=lambda x: x[1]):
        print(f"  dead letter: {env.kind} to {env.recipient}: {why}")


if __name__ == "__main__":
    main()
