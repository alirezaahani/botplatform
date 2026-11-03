"""Claiming and finishing runs in the database."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from botplatform.contract import Status
from botplatform.db import Run


def claim_next(session: Session, worker_id: str) -> Run | None:
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
    return run


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
