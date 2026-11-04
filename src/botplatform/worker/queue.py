"""Claiming, leasing and finishing runs in the database.

Every time comparison uses the database clock, so differences between containers do not matter.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from botplatform.contract import Status
from botplatform.db import Run, RunEvent


def _lease_end(lease_seconds: int):  # noqa: ANN202 - a SQL expression
    return func.now() + func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds)


def claim_next(session: Session, worker_id: str, lease_seconds: int = 30) -> Run | None:
    """Take the oldest queued run. `SKIP LOCKED` stops two workers claiming the same one."""
    run = session.scalar(
        select(Run)
        .where(Run.status == Status.QUEUED)
        .order_by(Run.queued_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if run is not None:
        run.status = Status.RUNNING
        run.started_at = func.now()
        run.worker_id = worker_id
        run.lease_expires_at = _lease_end(lease_seconds)
    return run


def renew(session: Session, run_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
    """Extend the lease. False means this worker no longer owns a running run."""
    result = session.execute(
        update(Run)
        .where(Run.id == run_id, Run.status == Status.RUNNING, Run.worker_id == worker_id)
        .values(lease_expires_at=_lease_end(lease_seconds))
    )
    return result.rowcount == 1


def reap_expired(session: Session) -> list[uuid.UUID]:
    """Mark every running run whose lease has expired as `error`/`worker_lost`."""
    ids = list(
        session.scalars(
            update(Run)
            .where(Run.status == Status.RUNNING, Run.lease_expires_at < func.now())
            .values(
                status=Status.ERROR,
                reason="worker_lost",
                error="The worker stopped renewing this run's lease, so it was presumed lost",
                ended_at=func.now(),
            )
            .returning(Run.id)
        )
    )
    session.add_all(RunEvent(run_id=run_id, type="worker_lost") for run_id in ids)
    return ids


def finish(
    session: Session,
    run_id: uuid.UUID,
    status: Status,
    reason: str | None = None,
    error: str | None = None,
) -> bool:
    """Set the final status, unless the run has already finished. Returns whether it did."""
    result = session.execute(
        update(Run)
        .where(Run.id == run_id, Run.status == Status.RUNNING)
        .values(status=status, reason=reason, error=error, ended_at=func.now())
    )
    return result.rowcount == 1
