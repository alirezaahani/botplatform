"""`run_in_child` and SIGTERM handling, with fake child commands instead of real bots."""

import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from botplatform.config import Settings
from botplatform.contract import Bot, BotResult, Status
from botplatform.db import Run
from botplatform.worker import child, queue
from botplatform.worker.main import run_in_child

# Spawns a grandchild in the same group (like Chrome), records its pid, then does `behavior`.
FAKE_CHILD = textwrap.dedent(
    """
    import subprocess, sys, time
    grandchild = subprocess.Popen(["sleep", "300"])
    open({pidfile!r}, "w").write(str(grandchild.pid))
    {behavior}
    """
)
HANG = "time.sleep(300)"
EXIT = "sys.exit(3)"


def fake_command(tmp_path: Path, behavior: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        FAKE_CHILD.format(pidfile=str(tmp_path / "pid"), behavior=behavior),
    ]


def grandchild_pid(tmp_path: Path) -> int:
    pidfile = tmp_path / "pid"
    deadline = time.monotonic() + 10
    while not (pidfile.exists() and pidfile.read_text()):
        assert time.monotonic() < deadline, "the fake child never started"
        time.sleep(0.05)
    return int(pidfile.read_text())


def is_dead(pid: int) -> bool:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def claimed_run(sessions: sessionmaker, worker_id: str = "w1") -> uuid.UUID:
    with sessions.begin() as session:
        run = Run(bot_id="arcaptcha", mode="headless")
        session.add(run)
        session.flush()
        queue.claim_next(session, worker_id, 30)
        return run.id


def state(sessions: sessionmaker, run_id: uuid.UUID) -> tuple[str, str | None]:
    with sessions() as session:
        run = session.get_one(Run, run_id)
        return run.status, run.reason


def settings(limit: int = 30, lease: int = 30, renew: float = 0.2) -> Settings:
    return Settings(run_time_limit_seconds=limit, lease_seconds=lease, lease_renew_seconds=renew)


def test_a_hung_child_and_its_grandchild_are_killed_at_the_time_limit(
    db: sessionmaker, tmp_path: Path
) -> None:
    run_id = claimed_run(db)
    started = time.monotonic()
    run_in_child(run_id, "w1", settings(limit=2), fake_command(tmp_path, HANG))
    assert time.monotonic() - started < 6
    assert state(db, run_id) == ("timeout", "run_time_limit")
    assert is_dead(grandchild_pid(tmp_path))


def test_a_child_that_exits_without_a_result_is_bot_process_died(
    db: sessionmaker, tmp_path: Path
) -> None:
    run_id = claimed_run(db)
    run_in_child(run_id, "w1", settings(), fake_command(tmp_path, EXIT))
    assert state(db, run_id) == ("error", "bot_process_died")
    assert is_dead(grandchild_pid(tmp_path))


def test_the_lease_is_renewed_while_the_child_runs(db: sessionmaker, tmp_path: Path) -> None:
    run_id = claimed_run(db)
    with db.begin() as session:  # a lease that would expire well before the child ends
        session.execute(text("UPDATE runs SET lease_expires_at = now() + interval '1 second'"))
    run_in_child(
        run_id, "w1", settings(limit=2, lease=30), fake_command(tmp_path, "time.sleep(1.5)")
    )
    # Renewed to ~30 s ahead, so the child's own exit (code 0) is what ended the run.
    assert state(db, run_id) == ("error", "bot_process_died")
    with db() as session:
        assert session.execute(
            text("SELECT lease_expires_at > now() + interval '10 seconds' FROM runs")
        ).scalar()


def test_losing_the_lease_kills_the_child_and_keeps_the_reapers_status(
    db: sessionmaker, tmp_path: Path
) -> None:
    run_id = claimed_run(db)

    def reaper() -> None:
        grandchild_pid(tmp_path)
        with db.begin() as session:
            session.execute(text("UPDATE runs SET lease_expires_at = now() - interval '1 second'"))
            queue.reap_expired(session)

    thread = threading.Thread(target=reaper)
    thread.start()
    run_in_child(run_id, "w1", settings(limit=20), fake_command(tmp_path, HANG))
    thread.join()
    assert state(db, run_id) == ("error", "worker_lost")
    assert is_dead(grandchild_pid(tmp_path))


def test_sigterm_kills_the_child_and_marks_the_run_worker_stopped(
    db: sessionmaker, tmp_path: Path
) -> None:
    run_id = claimed_run(db)
    code = textwrap.dedent(
        f"""
        import uuid
        from botplatform.config import Settings
        from botplatform.worker.main import run_in_child, stop_on_sigterm
        stop_on_sigterm()
        run_in_child(
            uuid.UUID({str(run_id)!r}), "w1", Settings(),
            {fake_command(tmp_path, HANG)!r},
        )
        """
    )
    worker = subprocess.Popen([sys.executable, "-c", code])
    pid = grandchild_pid(tmp_path)
    worker.send_signal(signal.SIGTERM)
    assert worker.wait(timeout=10) == 0
    assert state(db, run_id) == ("error", "worker_stopped")
    assert is_dead(pid)


def test_an_exception_raised_by_a_bot_becomes_an_unhandled_exception_result(
    db: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Exploding(Bot):
        def run(self, ctx: Any) -> BotResult:
            raise RuntimeError("it broke")

    monkeypatch.setattr(child, "BOTS", [Exploding("arcaptcha", "x", modes=("headless",))])
    result = child.execute(claimed_run(db))

    assert (result.status, result.reason) == (Status.ERROR, "unhandled_exception")
    assert "RuntimeError: it broke" in result.error
