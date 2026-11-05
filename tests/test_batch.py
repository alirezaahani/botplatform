"""The batch runner: planning and output with injected clocks, then the real queue."""

import threading
import time
import uuid
from collections import Counter

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from botplatform import batch
from botplatform.contract import Status
from botplatform.db import BotRecord, Run
from botplatform.worker import queue

A, B = ("arcaptcha", "headless"), ("arcaptcha-no-cdc", "headless")


def test_plan_has_every_combination_the_right_number_of_times():
    items = batch.plan(["a", "b", "c"], ["headless", "headful"], 4, seed=1)
    assert len(items) == 24
    assert Counter(items) == {(b, m): 4 for b in "abc" for m in ("headless", "headful")}


def test_plan_is_reproducible_by_seed_and_actually_shuffled():
    args = (["a", "b"], ["headless", "headful"], 5)
    assert batch.plan(*args, seed=7) == batch.plan(*args, seed=7)
    assert batch.plan(*args, seed=7) != batch.plan(*args, seed=8)
    ordered = sorted(batch.plan(*args, seed=7))
    assert batch.plan(*args, seed=7) != ordered


class Fake:
    """A queue, clock and sleep that never wait. Each run answers from `answers`, in order."""

    def __init__(self, answers: dict, lag: int = 0) -> None:
        self.answers = {combo: list(items) for combo, items in answers.items()}
        self.lag = lag  # polls that still say "running" before the answer
        self.now = 0.0
        self.sleeps: list[float] = []
        self.created: list[tuple[str, str]] = []
        self.runs: dict[uuid.UUID, tuple] = {}
        self.polls: Counter = Counter()

    def create(self, bot: str, mode: str) -> uuid.UUID:
        run_id = uuid.uuid4()
        self.created.append((bot, mode))
        self.runs[run_id] = (bot, mode)
        return run_id

    def status_of(self, run_id: uuid.UUID):
        self.polls[run_id] += 1
        if self.polls[run_id] <= self.lag:
            return "running", None, None
        combo = self.runs[run_id]
        if combo not in self.answers:
            return "running", None, None
        if not self.answers[combo]:
            return "success", None, "c"
        return self.answers[combo].pop(0)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now

    def run(self, items, **options) -> batch.Batch:
        lines: list[str] = []
        result = batch.run_batch(
            items, create=self.create, status_of=self.status_of, sleep=self.sleep,
            clock=self.clock, out=lines.append, **options,
        )  # fmt: skip
        self.lines = lines
        return result


BLOCKED = ("blocked", "captcha_blocked", "id1")


def test_run_batch_prints_a_line_per_run_and_pauses_between_runs_only():
    fake = Fake({A: [BLOCKED, ("success", None, "id2")]}, lag=2)
    result = fake.run([A, A], pause=10)
    assert fake.lines[0].startswith("1/2 arcaptcha headless blocked captcha_blocked id1 ")
    assert fake.lines[1].startswith("2/2 arcaptcha headless success - id2 ")
    assert [o.status for o in result.outcomes] == ["blocked", "success"]
    pauses = [s for s in fake.sleeps if s >= 10]  # polls are 1s
    assert pauses == [10]
    assert "arcaptcha headless: 2 runs: blocked/captcha_blocked 1, success 1" in batch.summary(
        result
    )


def test_a_run_that_never_finishes_is_reported_and_the_batch_carries_on():
    fake = Fake({A: []}, lag=10**9)
    result = fake.run([A, B], run_timeout=5, pause=0)
    assert [o.status for o in result.outcomes] == ["wait_timeout", "wait_timeout"]
    assert fake.lines[0].startswith("1/2 arcaptcha headless wait_timeout")


def test_ctrl_c_stops_cleanly_and_names_the_run_left_to_the_worker():
    fake = Fake({A: []}, lag=10**9)

    def interrupt(seconds: float) -> None:
        raise KeyboardInterrupt

    result = batch.run_batch(
        [A, B], create=fake.create, status_of=fake.status_of, sleep=interrupt,
        clock=fake.clock, out=lambda line: None,
    )  # fmt: skip
    assert result.interrupted and result.pending_run in fake.runs
    text = batch.summary(result)
    assert "Stopped by Ctrl-C" in text and "left to the worker" in text


def test_arguments_need_bots_and_default_to_both_modes():
    args = batch.parse_args(["--bots", "a,b"])
    assert (args.bots, args.modes, args.runs, args.pause) == (
        ["a", "b"], ["headless", "headful"], 10, 10,
    )  # fmt: skip
    with pytest.raises(SystemExit):
        batch.parse_args([])
    with pytest.raises(SystemExit):
        batch.parse_args(["--bots", "a", "--modes", ""])


def test_main_refuses_an_unknown_bot_or_unsupported_mode(clean_db: sessionmaker, capsys):
    with clean_db.begin() as session:
        session.add(BotRecord(id="solo", name="x", modes=["headless"]))
    assert batch.main(["--bots", "missing"]) == 2
    assert "missing" in capsys.readouterr().out
    assert batch.main(["--bots", "solo", "--modes", "headful"]) == 2
    assert "does not support mode 'headful'" in capsys.readouterr().out


def test_a_bot_with_its_own_modes_can_be_batched_and_unsupported_modes_exit_2(
    clean_db: sessionmaker, capsys
):
    with clean_db.begin() as session:
        session.add(BotRecord(id="plain", name="x", modes=["direct"]))
    assert batch.main(["--bots", "plain", "--modes", "headless"]) == 2
    assert "does not support mode 'headless'" in capsys.readouterr().out
    stop = threading.Event()

    def worker() -> None:
        while not stop.is_set():
            with clean_db.begin() as session:
                run = queue.claim_next(session, "w1")
                if run is not None:
                    queue.finish(session, run.id, Status.SUCCESS, None)
            time.sleep(0.05)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        code = batch.main(["--bots", "plain", "--modes", "direct", "--runs", "1", "--pause", "0"])
    finally:
        stop.set()
        thread.join()
    assert code == 0
    with clean_db() as session:
        assert [(r.bot_id, r.mode) for r in session.scalars(select(Run))] == [("plain", "direct")]


def test_batch_against_the_real_queue_with_a_stand_in_worker(db: sessionmaker):
    with db.begin() as session:
        session.add(BotRecord(id="arcaptcha-no-cdc", name="x", modes=["headless"]))
    stop = threading.Event()

    def worker() -> None:
        while not stop.is_set():
            with db.begin() as session:
                run = queue.claim_next(session, "w1")
                if run is not None:
                    queue.finish(session, run.id, Status.BLOCKED, "captcha_blocked")
                    run.challenge_id = "cid"
            time.sleep(0.05)

    thread = threading.Thread(target=worker)
    thread.start()

    def create(bot: str, mode: str) -> uuid.UUID:
        with db.begin() as session:
            return queue.enqueue(session, bot, mode).id

    def status_of(run_id: uuid.UUID):
        with db() as session:
            run = session.get_one(Run, run_id)
            return run.status, run.reason, run.challenge_id

    try:
        items = batch.plan(["arcaptcha", "arcaptcha-no-cdc"], ["headless"], 3, seed=5)
        result = batch.run_batch(
            items, create=create, status_of=status_of, sleep=time.sleep, clock=time.monotonic,
            pause=0, run_timeout=20, poll=0.05, out=lambda line: None,
        )  # fmt: skip
    finally:
        stop.set()
        thread.join()
    assert len(result.outcomes) == 6
    assert {o.status for o in result.outcomes} == {"blocked"}
    with db() as session:
        assert Counter(session.scalars(select(Run.bot_id))) == {
            "arcaptcha": 3,
            "arcaptcha-no-cdc": 3,
        }


def test_web_side_modules_import_without_selenium():
    """The web image has no Selenium. Importing a `bots` module there would crash the batch CLI."""
    import subprocess
    import sys

    code = (
        "import sys; sys.modules['selenium'] = None\n"
        "import botplatform.batch, botplatform.web.app, botplatform.web.stats, botplatform.stats\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
