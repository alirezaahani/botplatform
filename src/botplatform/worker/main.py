"""The worker loop: publish the bots, then run queued runs one at a time."""

import logging
import os
import signal
import socket
import subprocess
import sys
import time
import uuid

from sqlalchemy.orm import sessionmaker

from botplatform.bots import BOTS
from botplatform.config import Settings
from botplatform.contract import Status
from botplatform.db import session_factory
from botplatform.worker import queue, registry

log = logging.getLogger("botplatform.worker")


def run_in_child(sessions: sessionmaker, run_id: uuid.UUID, time_limit: int) -> None:
    """Run one bot in a new process group. At the time limit, kill the whole group."""
    child = subprocess.Popen(
        [sys.executable, "-m", "botplatform.worker.child", str(run_id)],
        start_new_session=True,
    )
    try:
        exit_code = child.wait(timeout=time_limit)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
        status, reason, error = (
            Status.TIMEOUT,
            "run_time_limit",
            f"The run exceeded the {time_limit} second limit",
        )
    else:
        # This only takes effect if the child exited without recording a result.
        status, reason, error = (
            Status.ERROR,
            "bot_process_died",
            f"The bot process exited with code {exit_code} without a result",
        )
    with sessions.begin() as session:
        queue.finish(session, run_id, status, reason, error)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    settings = Settings()
    sessions = session_factory()
    worker_id = socket.gethostname()

    registry.validate(BOTS)
    with sessions.begin() as session:
        registry.publish(session, BOTS)
    log.info("Worker %s published bots: %s", worker_id, [bot.id for bot in BOTS])

    while True:
        with sessions.begin() as session:
            run = queue.claim_next(session, worker_id)
            run_id = run.id if run else None
        if run_id is None:
            time.sleep(settings.worker_poll_seconds)
            continue
        log.info("Starting run %s", run_id)
        run_in_child(sessions, run_id, settings.run_time_limit_seconds)
        log.info("Finished run %s", run_id)


if __name__ == "__main__":
    main()
