"""Runs many bot runs one after another and prints one line for each, to measure profiles.

    docker compose run --rm web python -m botplatform.batch --profiles baseline,no-cdc --runs 10

It queues runs through the normal queue and waits for the worker to finish each, so a batch run
is a normal run in the history. The order is shuffled so that time of day or an IP reputation
that drifts cannot favour one profile.
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

from botplatform.profiles import PROFILES, bot_id
from botplatform.contract import ACTIVE_STATUSES
from botplatform.db import BotRecord, Run, session_factory
from botplatform.worker import queue

MODES = ("headless", "headful")
BLOCKED = ("blocked", "captcha_blocked")  # status and reason of a run the site blocked
Combo = tuple[str, str]  # bot id, mode


def plan(bots: list[str], modes: list[str], runs: int, seed: int) -> list[Combo]:
    """Every (bot, mode) `runs` times, in an order that depends only on `seed`."""
    items = [(bot, mode) for bot in bots for mode in modes for _ in range(runs)]
    random.Random(seed).shuffle(items)
    return items


def pause_seconds(pause: float, jitter: float, rng: random.Random) -> float:
    return pause + rng.uniform(0, jitter)


class EarlyStop:
    """Stops a combination after `limit` blocked runs in a row. 0 never stops."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._streak: Counter[Combo] = Counter()

    def record(self, combo: Combo, status: str, reason: str | None) -> None:
        self._streak[combo] = self._streak[combo] + 1 if (status, reason) == BLOCKED else 0

    def stopped(self, combo: Combo) -> bool:
        return self.limit > 0 and self._streak[combo] >= self.limit


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
    """What a batch did. `skipped` counts runs dropped by the early stop rule."""

    outcomes: list[Outcome]
    skipped: Counter[Combo]
    interrupted: bool = False
    pending_run: uuid.UUID | None = None  # a queued run left to the worker after Ctrl-C


def run_batch(
    items: list[Combo],
    *,
    create: Callable[[str, str], uuid.UUID],
    status_of: Callable[[uuid.UUID], tuple[str, str | None, str | None]],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    rng: random.Random,
    pause: float = 10,
    jitter: float = 5,
    run_timeout: float = 240,
    stop_after: int = 5,
    poll: float = 1.0,
    out: Callable[[str], None] = print,
) -> Batch:
    """Run `items` in order. `create`, `status_of`, `sleep` and `clock` are injected for tests."""
    batch = Batch([], Counter())
    stop = EarlyStop(stop_after)
    total = len(items)
    announced: set[Combo] = set()
    run_id: uuid.UUID | None = None
    try:
        for number, combo in enumerate(items, 1):
            if stop.stopped(combo):
                batch.skipped[combo] += 1
                if combo not in announced:
                    announced.add(combo)
                    out(
                        f"-- {combo[0]} {combo[1]}: {stop_after} blocked in a row, skipping the rest"
                    )
                continue
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
            stop.record(combo, status, reason)
            out(
                f"{number}/{total} {combo[0]} {combo[1]} {status} {reason or '-'} "
                f"{challenge_id or '-'} {seconds:.0f}s"
            )
            if number < total:
                sleep(pause_seconds(pause, jitter, rng))
    except KeyboardInterrupt:
        batch.interrupted = True
        batch.pending_run = run_id
    return batch


def summary(batch: Batch) -> str:
    lines = ["", "Summary"]
    combos = sorted({(o.bot, o.mode) for o in batch.outcomes} | set(batch.skipped))
    for combo in combos:
        counts = Counter(
            f"{o.status}/{o.reason}" if o.reason else o.status
            for o in batch.outcomes
            if (o.bot, o.mode) == combo
        )
        done = sum(counts.values())
        text = ", ".join(f"{name} {n}" for name, n in sorted(counts.items())) or "none"
        skipped = (
            f" (skipped {batch.skipped[combo]} by the early stop)" if batch.skipped[combo] else ""
        )
        lines.append(f"{combo[0]} {combo[1]}: {done} runs: {text}{skipped}")
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
    parser.add_argument("--profiles", default=",".join(PROFILES), help="comma separated names")
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument("--runs", type=int, default=10, help="per profile and mode")
    parser.add_argument("--pause", type=float, default=10, help="seconds between runs")
    parser.add_argument("--jitter", type=float, default=5, help="random 0..N seconds added")
    parser.add_argument("--run-timeout", type=float, default=240, help="seconds to wait for a run")
    parser.add_argument("--stop-after", type=int, default=5, help="blocked in a row; 0 = never")
    parser.add_argument("--seed", type=int, help="shuffle seed, for a reproducible order")
    args = parser.parse_args(argv)
    args.profiles = [p for p in args.profiles.split(",") if p]
    args.modes = [m for m in args.modes.split(",") if m]
    unknown = [p for p in args.profiles if p not in PROFILES]
    if unknown:
        parser.error(f"unknown profiles {unknown}; known: {', '.join(PROFILES)}")
    unknown = [m for m in args.modes if m not in MODES]
    if unknown:
        parser.error(f"unknown modes {unknown}; known: {', '.join(MODES)}")
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**32)
    bots = [bot_id(name) for name in args.profiles]
    sessions = session_factory()
    with sessions() as session:
        known = {b.id: b for b in session.scalars(select(BotRecord).where(BotRecord.active))}
    for bot in bots:
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

    items = plan(bots, args.modes, args.runs, seed)
    print(f"seed {seed}: {len(items)} runs. Use --seed {seed} to repeat this order.")
    batch = run_batch(
        items,
        create=create,
        status_of=status_of,
        sleep=time.sleep,
        clock=time.monotonic,
        rng=random.Random(seed + 1),
        pause=args.pause,
        jitter=args.jitter,
        run_timeout=args.run_timeout,
        stop_after=args.stop_after,
        out=lambda line: print(line, flush=True),
    )
    print(summary(batch))
    return 130 if batch.interrupted else 0


if __name__ == "__main__":
    sys.exit(main())
