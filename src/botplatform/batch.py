"""Runs many bot runs one after another and prints one line for each, to compare bots.

    docker compose run --rm web python -m botplatform.batch --bots arcaptcha,arcaptcha-solver --runs 10

It queues runs through the normal queue and waits for the worker to finish each, so a batch run
is a normal run in the history. The order is shuffled so that time of day or an IP reputation
that drifts cannot favour one bot.
"""

import argparse
import random
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select

from botplatform.contract import ACTIVE_STATUSES
from botplatform.db import BotRecord, Run, session_factory
from botplatform.worker import queue

MODES = ("headless", "headful")
RUN_TIMEOUT = 240  # seconds to wait for one run; the worker's own limit is shorter
Combo = tuple[str, str]  # bot id, mode


def plan(bots: list[str], modes: list[str], runs: int, seed: int) -> list[Combo]:
    """Every (bot, mode) `runs` times, in an order that depends only on `seed`."""
    items = [(bot, mode) for bot in bots for mode in modes for _ in range(runs)]
    random.Random(seed).shuffle(items)
    return items


@dataclass
class Outcome:
    bot: str
    mode: str
    status: str  # a run status, or "wait_timeout" if the batch stopped waiting for it
    reason: str | None
    challenge_id: str | None
    seconds: float


@dataclass
class Batch:
    """What a batch did."""

    outcomes: list[Outcome]
    interrupted: bool = False
    pending_run: uuid.UUID | None = None  # a queued run left to the worker after Ctrl-C


def run_batch(
    items: list[Combo],
    *,
    create: Callable[[str, str], uuid.UUID],
    status_of: Callable[[uuid.UUID], tuple[str, str | None, str | None]],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    pause: float = 10,
    run_timeout: float = RUN_TIMEOUT,
    poll: float = 1.0,
    out: Callable[[str], None] = print,
) -> Batch:
    """Run `items` in order. `create`, `status_of`, `sleep` and `clock` are injected for tests."""
    batch = Batch([])
    total = len(items)
    run_id: uuid.UUID | None = None
    try:
        for number, combo in enumerate(items, 1):
            started = clock()
            run_id = create(*combo)
            status, reason, challenge_id = status_of(run_id)
            while status in ACTIVE_STATUSES and clock() - started < run_timeout:
                sleep(poll)
                status, reason, challenge_id = status_of(run_id)
            if status in ACTIVE_STATUSES:
                status = "wait_timeout"  # the run itself may still finish later
            run_id = None
            seconds = clock() - started
            batch.outcomes.append(Outcome(*combo, status, reason, challenge_id, seconds))
            out(
                f"{number}/{total} {combo[0]} {combo[1]} {status} {reason or '-'} "
                f"{challenge_id or '-'} {seconds:.0f}s"
            )
            if number < total:
                sleep(pause)
    except KeyboardInterrupt:
        batch.interrupted = True
        batch.pending_run = run_id
    return batch


def summary(batch: Batch) -> str:
    lines = ["", "Summary"]
    combos = sorted({(o.bot, o.mode) for o in batch.outcomes})
    for combo in combos:
        counts = Counter(
            f"{o.status}/{o.reason}" if o.reason else o.status
            for o in batch.outcomes
            if (o.bot, o.mode) == combo
        )
        done = sum(counts.values())
        text = ", ".join(f"{name} {n}" for name, n in sorted(counts.items())) or "none"
        lines.append(f"{combo[0]} {combo[1]}: {done} runs: {text}")
    if batch.interrupted:
        lines.append("Stopped by Ctrl-C.")
        if batch.pending_run:
            lines.append(
                f"Run {batch.pending_run} was already queued and is left to the worker. "
                "It will show in the history."
            )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m botplatform.batch", description=__doc__)
    parser.add_argument("--bots", required=True, help="comma separated bot ids")
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument("--runs", type=int, default=10, help="per bot and mode")
    parser.add_argument("--pause", type=float, default=10, help="seconds between runs")
    parser.add_argument("--seed", type=int, help="shuffle seed, for a reproducible order")
    args = parser.parse_args(argv)
    args.bots = [b for b in args.bots.split(",") if b]
    args.modes = [m for m in args.modes.split(",") if m]
    if not args.bots:
        parser.error("--bots needs at least one bot id")
    unknown = [m for m in args.modes if m not in MODES]
    if unknown:
        parser.error(f"unknown modes {unknown}; known: {', '.join(MODES)}")
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**32)
    sessions = session_factory()
    with sessions() as session:
        known = {b.id: b for b in session.scalars(select(BotRecord).where(BotRecord.active))}
    for bot in args.bots:
        if bot not in known:
            print(f"Bot '{bot}' is not published by a worker. Is the worker running?")
            return 2
        for mode in args.modes:
            if mode not in known[bot].modes:
                print(f"Bot '{bot}' does not support mode '{mode}'")
                return 2

    def create(bot: str, mode: str) -> uuid.UUID:
        with sessions.begin() as session:
            return queue.enqueue(session, bot, mode).id

    def status_of(run_id: uuid.UUID) -> tuple[str, str | None, str | None]:
        with sessions() as session:
            run = session.get_one(Run, run_id)
            return run.status, run.reason, run.challenge_id

    items = plan(args.bots, args.modes, args.runs, seed)
    print(f"seed {seed}: {len(items)} runs. Use --seed {seed} to repeat this order.")
    batch = run_batch(
        items,
        create=create,
        status_of=status_of,
        sleep=time.sleep,
        clock=time.monotonic,
        pause=args.pause,
        out=lambda line: print(line, flush=True),
    )
    print(summary(batch))
    return 130 if batch.interrupted else 0


if __name__ == "__main__":
    sys.exit(main())
