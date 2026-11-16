"""Replay JSONL envelopes in recorded arrival order; timings are non-deterministic."""
import argparse
import hashlib
import json
import math
import platform
from time import perf_counter_ns
from .book import Book, decode


def replay(lines, venue):
    book = Book(venue)
    digest = hashlib.sha256()
    times = {key: [] for key in ("decode", "book", "features", "total")}
    count = 0
    last_received = -1
    last_session = None
    for line in lines:
        envelope = json.loads(line)
        received = envelope["received_ns"]
        if not isinstance(received, int) or received < last_received:
            raise ValueError("Replay must be in recorded arrival order")
        last_received = received
        session = envelope.get("session", 0)
        if session != last_session:
            book.reset()
            last_session = session
        start = perf_counter_ns()
        message = decode(envelope["raw"])
        decoded = perf_counter_ns()
        changed = book.apply(message, received)
        updated = perf_counter_ns()
        if not changed:
            continue
        features = book.features(received)
        end = perf_counter_ns()
        digest.update(json.dumps({"received_ns": received, "features": features},
                                 sort_keys=True).encode())
        count += 1
        for key, value in zip(times, (decoded-start, updated-decoded, end-updated, end-start)):
            times[key].append(value)
    if not count:
        raise ValueError("No validated book events")
    def summary(values):
        values = sorted(values)
        return {f"p{p}_ns": values[max(0, math.ceil(len(values)*p/100)-1)]
                for p in (50, 95, 99)}
    return {"book_events": count, "feature_sha256": digest.hexdigest(),
            "latency": {k: summary(v) for k, v in times.items()},
            "python": platform.python_version(), "platform": platform.platform(),
            "scope": "CPU processing only; excludes IO/network; no execution decisions",
            "final_features": features}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path")
    p.add_argument("--venue", choices=["kraken", "coinbase"], required=True)
    args = p.parse_args()
    with open(args.path, encoding="utf-8") as source:
        print(json.dumps(replay(source, args.venue), indent=2))
