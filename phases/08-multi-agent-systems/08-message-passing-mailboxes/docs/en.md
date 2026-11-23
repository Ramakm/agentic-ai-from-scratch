# Message Passing and Mailboxes

> Give each agent a mailbox and let it handle one message at a time, sharing nothing. That's the actor model, and it makes concurrency easy to reason about. It also brings the network's problems with it: messages get lost, duplicated, piled up or stuck, and each one needs a deliberate answer.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 8 · Lessons 2 and 5; Phase 2 · Lesson 7
**Time:** ~50 minutes

## Learning Objectives

- Build actors: an agent with private state, a mailbox, and a loop that handles one message at a time.
- Implement request/reply with message ids and correlation ids, timeouts and resends (at-least-once delivery).
- Make handlers idempotent by deduplicating on message id, so resends and duplicates don't repeat side effects.
- Use bounded mailboxes for backpressure, and a dead-letter queue for messages that can't be delivered or handled.

## The Problem

Lesson 5's blackboard shared one store between agents, so it needed locks and versioned writes. The alternative is to share nothing: each agent owns its state, and the only way to affect it is to send it a message. No locks, no lost updates. Each agent handles its messages in order, so its own code never runs concurrently with itself.

The price shows up the moment agents run in different processes or machines, which is where production multi-agent systems end up. A request is sent and no reply comes. Was the request lost, or the reply? If you resend, the receiver might do the work twice: charge the customer twice, send the email twice. A burst of work arrives faster than an agent can process it, and its queue grows without limit. One malformed message crashes the handler every time it's retried. None of these are model problems, and models don't fix them.

## The Concept

```
 planner (Requester)                  bus (may drop or duplicate)              billing (Actor)
   ask(id=planner-7) ───── send ─────────────► mailbox [m..m..m] ──► handle one at a time
        │ waits on correlation id                                        │ seen planner-7? skip
        │ timeout? resend same id                                        │ private state: charges
   ◄─── reply(correlation_id=planner-7) ◄───────────────────────────────┘
```

| Problem | Mechanism |
|---------|-----------|
| Which reply answers which request? | Every message has an `id`; replies carry `correlation_id` = the request's id |
| No reply | Timeout and resend the **same** message (same id): at-least-once delivery |
| Duplicates (from resends or the network) | Receivers remember ids they've handled and skip repeats: idempotent handling |
| Work arrives faster than it's handled | Bounded mailbox: the producer waits or the message is rejected (backpressure) |
| A message that always fails | Retry a few times, then move it to a dead-letter queue for a human or a repair job |
| A message for an agent that doesn't exist | Dead-letter it with the reason, instead of losing it |

"Exactly once" delivery isn't something a network can promise. What you can build is an **exactly-once effect**: at-least-once delivery plus idempotent handling.

## Build It

```bash
cd code
python3 main.py
```

Agents here are plain handlers with no model, so the run is deterministic. The unreliable network is simulated: whether a delivery is dropped or duplicated is decided by a hash of the message id and attempt, so it's identical on every run.

### Step 1: actors

```python
class Actor:
    def _loop(self):
        while True:
            env = self.mailbox.get()
            ...
            try:
                self.handle(env)
            except Exception as e:
                n = self.failures[env.id] = self.failures.get(env.id, 0) + 1
                if n >= self.max_attempts:
                    self.bus.dead_letters.append((env, f"{type(e).__name__}: {e} after {n} attempts"))
                else:
                    self.mailbox.put(env)
```

One thread per actor, one message at a time. A real agent's `handle` calls a model or tools; that's slow, which is exactly why it gets its own queue.

### Step 2: request/reply over a lossy bus

```python
def ask(self, recipient, kind, body, timeout=0.1, retries=4):
    env = Envelope(kind, body, self.name, recipient, id=f"{self.name}-{self.asked}")
    ...
    for attempt in range(1, retries + 2):
        env.attempt = attempt
        self.bus.send(env)          # same id every time: receivers can recognise a resend
        try:
            return box.get(timeout=timeout)
```

The planner asks billing to charge for 40 research jobs, over a bus that drops 15% of deliveries and duplicates 10%:

```text
1. Request/reply with correlation ids over a lossy bus (15% dropped, 10% duplicated)
  billing without dedupe       : 40 jobs, 40 answered, 53 charges for 40 jobs (sends 107, dropped 15, duplicated 8)
  billing dedupes by message id: 40 jobs, 40 answered, 40 charges for 40 jobs (sends 107, dropped 15, duplicated 8)
```

Resending made sure every job got an answer. Without deduplication, 13 jobs were charged twice: some because the network duplicated the request, some because billing charged, the reply was lost, and the planner resent. Billing had no way to know the second request was the same as the first, except by its id.

### Step 3: backpressure

A burst of 30 messages arrives while the consumer is busy:

```text
2. Backpressure: a burst of 30 messages while the consumer is busy
  unbounded-ish mailbox       : accepted 30, rejected  0, processed 30, peak mailbox depth 30
  bounded (5), drop when full : accepted  5, rejected 25, processed  5, peak mailbox depth  5
  bounded (5), producer waits : accepted 30, rejected  0, processed 30, peak mailbox depth  5, producer had to wait
```

An unbounded mailbox accepts everything, and in a long-running system that's how memory and latency grow until something falls over. A bounded mailbox forces a choice: reject (and the producer must handle the rejection), or make the producer wait, which slows it to the consumer's pace. For agents, waiting is usually right for internal work, and rejecting with a "try later" is right at the edge, where users or other systems call in.

### Step 4: dead letters

```text
3. Poison message and unknown recipient
  summariser processed 1 message(s)
  dead letter: summarise to summariser: ValueError: cannot decode input after 3 attempts
  dead letter: summarise to translator: no such recipient
```

The garbage message failed three times and was set aside, and the normal message behind it still got processed. Without a dead-letter queue, a poison message either blocks its mailbox forever or disappears without a trace.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Technology | Mailbox equivalent |
|------------|-------------------|
| Erlang/Elixir processes, Akka actors | The original actor model: mailboxes, supervisors, "let it crash" |
| Ray actors | Python actors with method-call messages, for distributed agents |
| Message brokers (RabbitMQ, SQS, Kafka, NATS) | Durable queues with acks, redelivery, dead-letter queues, consumer limits |
| Agent frameworks' event-driven runtimes | Agents subscribing to topics and publishing messages (for example AutoGen's actor-based core) |

Brokers give you durable mailboxes and redelivery for free. They don't give you idempotent handlers: that's always your code.

## Ship It

`outputs/skill-agent-messaging-reliability.md` is a skill for making message-passing agents reliable: envelope fields, correlation, timeouts and resend policy, idempotency keys and where to store them, mailbox bounds and backpressure policy per edge, and dead-letter handling with alerting.

## Exercises

1. **Easy.** Set the drop rate to 40%. How many resends are needed, and do any requests run out of retries? What should the planner do then?
2. **Medium.** Billing's `seen` set grows forever. Replace it with a store that keeps ids for 10 minutes. What's the risk if a resend arrives after 11?
3. **Medium.** Add a supervisor actor that restarts a crashed actor (its thread dies) and re-delivers its unacknowledged messages. Which messages could be processed twice now?
4. **Hard.** Put two billing actors behind one queue (competing consumers). What happens to deduplication when the duplicate of a request goes to the other instance? Fix it.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Actor | "Agent with an inbox" | Private state + mailbox + one-at-a-time handler; communicates only by messages |
| Correlation id | "Request id" | The request's id, copied into the reply so the sender can match them |
| At-least-once delivery | "Retries" | Resending until acknowledged; duplicates are possible |
| Idempotent handler | "Safe to retry" | Processing the same message twice has the same effect as once |
| Backpressure | "Slow down" | A full mailbox making producers wait or get rejected |
| Dead-letter queue | "DLQ" | Where undeliverable or repeatedly failing messages go for inspection |

## Further Reading

- [Hewitt, Bishop and Steiger, A Universal Modular ACTOR Formalism for Artificial Intelligence (1973)](https://www.ijcai.org/Proceedings/73/Papers/027B.pdf)
- [Joe Armstrong, Making reliable distributed systems in the presence of software errors (2003)](https://erlang.org/download/armstrong_thesis_2003.pdf)
- [Ray, Actors](https://docs.ray.io/en/latest/ray-core/actors.html)
- [AWS, Amazon SQS dead-letter queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html)
- [Martin Kleppmann, Designing Data-Intensive Applications](https://dataintensive.net/)
