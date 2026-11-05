"""Queues runs one after another, in a shuffled order, and prints one line for each.

    docker compose run --rm web python -m botplatform.batch --bots arcaptcha,example --runs 10

Each run goes through the normal queue, so it is a normal run in the history (see `/stats`).
"""

import argparse
import random
import sys
import time

from botplatform.contract import ACTIVE_STATUSES
from botplatform.db import Run, SessionLocal
from botplatform.worker import queue

parser = argparse.ArgumentParser(prog="python -m botplatform.batch")
parser.add_argument("--bots", required=True, help="comma separated bot ids")
parser.add_argument("--modes", default="headless,headful")
parser.add_argument("--runs", type=int, default=10, help="per bot and mode")
parser.add_argument("--pause", type=float, default=10, help="seconds between runs")


def main() -> int:
    args = parser.parse_args()
    bots, modes = args.bots.split(","), args.modes.split(",")
    try:  # every bot and mode, before any run is queued
        with SessionLocal() as session:
            for bot in bots:
                for mode in modes:
                    queue.check_launch(session, bot, mode)
    except queue.LaunchRefused as refused:
        print(refused)
        return 2

    items = [(bot, mode) for bot in bots for mode in modes for _ in range(args.runs)]
    random.shuffle(items)
    for number, (bot, mode) in enumerate(items, 1):
        started = time.monotonic()
        with SessionLocal.begin() as session:
            run_id = queue.enqueue(session, bot, mode).id
        while True:
            with SessionLocal() as session:
                run = session.get_one(Run, run_id)
                if run.status not in ACTIVE_STATUSES:
                    break
            time.sleep(1)
        seconds = time.monotonic() - started
        print(
            f"{number}/{len(items)} {bot} {mode} {run.status} {run.reason or '-'} "
            f"{run.challenge_id or '-'} {seconds:.0f}s",
            flush=True,
        )
        if number < len(items):
            time.sleep(args.pause)
    return 0


if __name__ == "__main__":
    sys.exit(main())
