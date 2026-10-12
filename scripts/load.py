"""Bounded HTTP load for local observability. Explicitly rejects remote hosts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import time
from urllib.parse import urlparse
from urllib.request import urlopen

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://localhost:8000/api/events/1/seats")
parser.add_argument("--seconds", type=int, default=30)
parser.add_argument("--workers", type=int, default=4)
args = parser.parse_args()
if urlparse(args.url).hostname not in {"localhost", "127.0.0.1", "backend"}:
    raise SystemExit("Only local SeatLock load is permitted")
if not 1 <= args.seconds <= 120 or not 1 <= args.workers <= 16:
    raise SystemExit("Bounded load: 1–120 seconds, 1–16 workers")
deadline = time.monotonic() + args.seconds

# Fail before applying load if a port-forward or the target app is unavailable.
try:
    with urlopen(args.url, timeout=5) as response:
        response.read()
except OSError as error:
    raise SystemExit("Local target is unavailable; start the app/port-forward before loading: " + str(error))


def worker(_):
    completed, failed = 0, 0
    while time.monotonic() < deadline:
        try:
            with urlopen(args.url, timeout=3) as response:  # noqa: S310 - local host allowlist above
                response.read()
                completed += 1
        except OSError:
            failed += 1
        time.sleep(0.02)
    return completed, failed


with ThreadPoolExecutor(max_workers=args.workers) as pool:
    outcomes = list(pool.map(worker, range(args.workers)))
print({"completed": sum(x[0] for x in outcomes), "failed": sum(x[1] for x in outcomes),
       "duration_seconds": args.seconds, "workers": args.workers})
