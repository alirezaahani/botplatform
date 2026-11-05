"""The run queue against a real Postgres: claiming, leases and reaping."""

import threading
import time
import uuid
from datetime import timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import sessionmaker

from botplatform.contract import Status
from botplatform.db import Run, RunEvent
from botplatform.worker import queue


def add_runs(sessions: sessionmaker, count: int) -> list[uuid.UUID]:
    """Queued runs, each with a distinct queued_at (the transaction time is shared otherwise)."""
    ids = []
    with sessions.begin() as session:
        for i in range(count):
            run = Run(bot_id="arcaptcha", mode="headless")
            session.add(run)
            session.flush()
            session.execute(
                update(Run)
                .where(Run.id == run.id)
                .values(queued_at=func.now() + timedelta(milliseconds=i))
            )
            ids.append(run.id)
    return ids


def get(sessions: sessionmaker, run_id: uuid.UUID) -> Run:
    with sessions() as session:
        return session.get_one(Run, run_id)


def claim(sessions: sessionmaker, worker: str = "w1", lease: int = 30) -> uuid.UUID | None:
    with sessions.begin() as session:
        run = queue.claim_next(session, worker, lease)
        return run.id if run else None


def expire(sessions: sessionmaker, run_id: uuid.UUID) -> None:
    with sessions.begin() as session:
        session.execute(
            text("UPDATE runs SET lease_expires_at = now() - interval '1 second' WHERE id = :i"),
            {"i": run_id},
        )


def test_claim_is_fifo(db: sessionmaker) -> None:
    ids = add_runs(db, 3)
    assert [claim(db), claim(db), claim(db), claim(db)] == [*ids, None]


def test_claim_marks_the_run_running_with_a_lease(db: sessionmaker) -> None:
    (run_id,) = add_runs(db, 1)
    claim(db, "w1", 30)
    run = get(db, run_id)
    assert (run.status, run.worker_id) == (Status.RUNNING, "w1")
    assert run.started_at is not None and run.lease_expires_at is not None
    assert run.lease_expires_at > run.started_at


def test_concurrent_claims_never_duplicate_or_lose_a_run(db: sessionmaker) -> None:
    ids = set(add_runs(db, 40))
    claimed: list[uuid.UUID] = []
    lock = threading.Lock()

    def worker(name: str) -> None:
        while (run_id := claim(db, name)) is not None:
            with lock:
                claimed.append(run_id)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(claimed) == len(ids)
    assert set(claimed) == ids


def test_finish_does_not_overwrite_a_final_status(db: sessionmaker) -> None:
    (run_id,) = add_runs(db, 1)
    claim(db)
    with db.begin() as session:
        assert queue.finish(session, run_id, Status.SUCCESS)
    with db.begin() as session:
        assert not queue.finish(session, run_id, Status.ERROR, "late")
    run = get(db, run_id)
    assert (run.status, run.reason) == ("success", None)


def test_renew_extends_the_lease(db: sessionmaker) -> None:
    (run_id,) = add_runs(db, 1)
    claim(db, "w1", 5)
    before = get(db, run_id).lease_expires_at
    assert before is not None
    time.sleep(0.05)
    with db.begin() as session:
        assert queue.renew(session, run_id, "w1", 60)
    after = get(db, run_id).lease_expires_at
    assert after is not None and after > before


def test_renew_refuses_another_worker_or_a_run_that_is_not_running(db: sessionmaker) -> None:
    queued, running = add_runs(db, 2)
    claim(db, "w1")  # takes `queued`, the oldest
    with db.begin() as session:
        assert not queue.renew(session, running, "w1", 30)  # still queued
        assert not queue.renew(session, queued, "w2", 30)  # someone else's
        queue.finish(session, queued, Status.SUCCESS)
        assert not queue.renew(session, queued, "w1", 30)  # finished


def test_reap_expired_marks_only_expired_running_runs(db: sessionmaker) -> None:
    dead, alive, waiting = add_runs(db, 3)
    claim(db)
    claim(db)
    expire(db, dead)
    with db.begin() as session:
        assert queue.reap_expired(session) == [dead]
    run = get(db, dead)
    assert (run.status, run.reason) == ("error", "worker_lost")
    assert run.error and run.ended_at
    assert get(db, alive).status == "running"
    assert get(db, waiting).status == "queued"
    with db.begin() as session:
        types = list(session.scalars(select(RunEvent.type).where(RunEvent.run_id == dead)))
        assert types == ["worker_lost"]
        assert queue.reap_expired(session) == []


def test_a_late_finish_after_reaping_changes_nothing(db: sessionmaker) -> None:
    (run_id,) = add_runs(db, 1)
    claim(db)
    expire(db, run_id)
    with db.begin() as session:
        queue.reap_expired(session)
    with db.begin() as session:
        assert not queue.finish(session, run_id, Status.SUCCESS)
    assert (get(db, run_id).status, get(db, run_id).reason) == ("error", "worker_lost")
