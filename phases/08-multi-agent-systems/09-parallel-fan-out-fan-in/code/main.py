"""Parallel fan-out / fan-in: send many independent subtasks to workers at once, then merge.
Concurrency limits, rate limits, tail latency, timeouts, hedging, quorums, and reducing results
that don't fit one context window.

    python3 main.py

Worker latencies are SIMULATED (seeded, with a heavy tail like real model APIs) and scheduled with
a small discrete-event simulation, so the timings below are exact and reproducible. `fan_out` is
the real threaded implementation; the tests run it with short sleeps.
"""
from __future__ import annotations

import concurrent.futures as cf
import heapq
import random
import threading
import time

# --------------------------------------------------------------------------------------------
# The workload: 24 documents to summarise
# --------------------------------------------------------------------------------------------


def latencies(n: int = 24, seed: int = 16) -> list[float]:
    """Most calls take 3-6 s; about 1 in 8 is slow (15-40 s): the tail every API has."""
    rng = random.Random(seed)
    return [round(rng.uniform(15, 40) if rng.random() < 0.125 else rng.uniform(3, 6), 1) for _ in range(n)]


SUMMARY_TOKENS = 600
WINDOW = 8000          # what the synthesiser can read at once
RATE_LIMIT = 8         # the provider allows 8 requests in flight


# --------------------------------------------------------------------------------------------
# Discrete-event scheduling
# --------------------------------------------------------------------------------------------


def schedule(lat: list[float], slots: int, timeout: float | None = None, hedge_after: float | None = None,
             backoff_429: float = 2.0, limit: int = RATE_LIMIT) -> dict:
    """Discrete-event run of len(lat) tasks with `slots` client workers against a provider that allows
    `limit` requests in flight. A request over the limit gets a 429 and the worker retries after
    `backoff_429` seconds.
    - timeout: a task still running after this long is abandoned (no result), freeing its slot
    - hedge_after: a task still running after this long gets a duplicate request that takes a typical
      4.5 s; whichever finishes first wins (the duplicate's own slot use is ignored here)"""
    events = [(0.0, w) for w in range(slots)]      # (time a worker is free, worker id)
    heapq.heapify(events)
    in_flight: list[float] = []                    # end times of requests the provider is serving
    queue_ = list(range(len(lat)))
    finish: dict[int, float] = {}
    calls = errors = 0
    last = 0.0
    pending: dict[int, int] = {}                   # worker -> task it's retrying
    while events:
        t, w = heapq.heappop(events)
        task = pending.pop(w, None)
        if task is None:
            if not queue_:
                continue
            task = queue_.pop(0)
        in_flight = [e for e in in_flight if e > t]
        calls += 1
        if len(in_flight) >= limit:
            errors += 1
            pending[w] = task
            heapq.heappush(events, (t + backoff_429, w))
            continue
        d = lat[task]
        end = t + d
        if hedge_after is not None and d > hedge_after:
            calls += 1
            end = min(end, t + hedge_after + 4.5)
        if timeout is not None and end - t > timeout:
            end = t + timeout
        else:
            finish[task] = end
        in_flight.append(end)
        last = max(last, end)
        heapq.heappush(events, (end, w))
    return {"finish": finish, "calls": calls, "errors": errors, "makespan": last}


def quorum_time(finish: dict[int, float], n: int, fraction: float) -> tuple[float, int]:
    need = int(n * fraction + 0.999)
    times = sorted(finish.values())
    return (times[need - 1], need) if len(times) >= need else (float("inf"), len(times))


# --------------------------------------------------------------------------------------------
# Fan-in: reduce
# --------------------------------------------------------------------------------------------


def reduce_plan(n_results: int, per_result: int = SUMMARY_TOKENS, window: int = WINDOW,
                group_tokens: int = 500) -> dict:
    """Concatenate if it fits; otherwise reduce in groups (tree) until it does."""
    if n_results * per_result <= window:
        return {"levels": 1, "calls": 1, "final_input": n_results * per_result}
    level, items, calls = 0, n_results, 0
    per = per_result
    while items * per > window:
        group = max(2, window // per)
        items, per = -(-items // group), group_tokens
        calls += items
        level += 1
    return {"levels": level + 1, "calls": calls + 1, "final_input": items * per}


# --------------------------------------------------------------------------------------------
# A real threaded fan-out (used by the tests with short sleeps)
# --------------------------------------------------------------------------------------------


def fan_out(fn, items, max_workers: int, timeout: float | None = None) -> tuple[dict, dict]:
    """Run fn over items with at most max_workers in flight. Returns (results, errors) keyed by index.
    Items not finished by `timeout` seconds after the start are reported as errors."""
    results, errors = {}, {}
    pool = cf.ThreadPoolExecutor(max_workers=max_workers)
    futures = {pool.submit(fn, item): i for i, item in enumerate(items)}
    try:
        for fut in cf.as_completed(futures, timeout=timeout):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:  # one failure doesn't sink the batch
                errors[i] = f"{type(e).__name__}: {e}"
    except cf.TimeoutError:
        for fut, i in futures.items():
            if i not in results and i not in errors:
                fut.cancel()
                errors[i] = "timed out"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return results, errors


def main() -> None:
    lat = latencies()
    n = len(lat)
    slow = sorted(lat, reverse=True)[:3]
    print(f"{n} documents; worker latency 3-6 s typically, slowest three: {slow} s (simulated)\n")
    print(f"  {'strategy':<44} {'done':>5} {'time':>7} {'calls':>6} {'429s':>5}")
    rows = [
        ("sequential (1 worker)", schedule(lat, 1)),
        ("all at once (24 workers, provider limit 8)", schedule(lat, 24)),
        ("bounded: 8 workers", schedule(lat, 8)),
        ("bounded + 12 s timeout per task", schedule(lat, 8, timeout=12)),
        ("bounded + hedge after 8 s", schedule(lat, 8, hedge_after=8)),
    ]
    for label, r in rows:
        print(f"  {label:<44} {len(r['finish']):>3}/{n} {r['makespan']:>6.1f}s {r['calls']:>6} {r['errors']:>5}")
    t, need = quorum_time(schedule(lat, 8)["finish"], n, 0.8)
    print(f"  {'bounded: stop at a quorum of 80%':<44} {need:>3}/{n} {t:>6.1f}s {'24*':>6} {0:>5}")
    print("  * the quorum run started all 24 calls; the last ones are cancelled or ignored")

    print(f"\nFan-in: {n} summaries x {SUMMARY_TOKENS} tokens into an {WINDOW}-token synthesiser")
    for k in (8, 13, 24, 100):
        p = reduce_plan(k)
        shape = "concatenate" if p["levels"] == 1 else f"tree, {p['levels']} levels"
        print(f"  {k:>3} results: {shape:<16} {p['calls']:>3} reduce call(s), final input {p['final_input']:>5} tokens")


if __name__ == "__main__":
    main()
