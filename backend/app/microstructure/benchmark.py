"""Synthetic normalized price-level benchmark; never market or strategy evidence."""
import argparse
import json
import math
import platform
import subprocess
import tempfile
import time
from pathlib import Path


def operations(count):
    for i in range(count):
        side = i % 2
        level = (i // 2) % 100
        price = 100000 - level if side == 0 else 100100 + level
        # A nonempty best level is always retained.
        quantity = 0 if i % 7 == 0 and level != 0 else i % 97 + 1
        yield side, price, quantity


def percentiles(values):
    values = sorted(values)
    return {f"p{p}_ns": values[math.ceil(len(values)*p/100)-1] for p in (50,95,99)}


def python_book(rows):
    bids, asks = {100000: 1}, {100100: 1}
    checksum = 0
    latency = []
    for side, price, quantity in rows:
        start = time.perf_counter_ns()
        book = bids if side == 0 else asks
        if quantity:
            book[price] = quantity
        else:
            book.pop(price, None)
        checksum += max(bids) + min(asks)
        latency.append(time.perf_counter_ns() - start)
    return {"checksum": checksum, "events": len(rows), **percentiles(latency)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events", type=int, default=20000)
    a = p.parse_args()
    if a.events < 200:
        p.error("At least 200 events required")
    rows = list(operations(a.events))
    source = Path(__file__).resolve().parents[2] / "benchmarks/book.cpp"
    with tempfile.TemporaryDirectory() as directory:
        binary = Path(directory)/"book"
        subprocess.run(["g++", "-O3", "-std=c++17", str(source), "-o", str(binary)], check=True)
        payload = "".join(f"{s} {p} {q}\n" for s,p,q in rows)
        cpp = json.loads(subprocess.run([str(binary)], input=payload, text=True,
                                       capture_output=True, check=True).stdout)
        python = python_book(rows)
    if cpp["checksum"] != python["checksum"] or cpp["events"] != python["events"]:
        raise RuntimeError("Implementation parity failed")
    print(json.dumps({"dataset": "deterministic synthetic integer price/size updates",
        "scope": "update + best bid/ask only; excludes IO, parsing, venue CRC, features",
        "python": python, "cpp": cpp, "platform": platform.platform(),
        "python_version": platform.python_version(),
        "compiler": subprocess.run(["g++", "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0],
        "caveat": "Python dict scans vs C++ ordered map; language and data-structure effects are confounded."}, indent=2))


if __name__ == "__main__":
    main()
