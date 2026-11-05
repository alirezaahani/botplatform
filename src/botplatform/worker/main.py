"""The worker loop: publish the bots, then run queued runs one at a time."""

import logging
import os
import signal
import socket
import subprocess
import sys
import time
import uuid

from botplatform.bots import BOTS
from botplatform.config import Settings
from botplatform.contract import Status
from botplatform.db import SessionLocal
from botplatform.worker import queue, registry

log = logging.getLogger("botplatform.worker")


def kill_group(child: subprocess.Popen) -> None:
    """Kill the child's whole process group, which includes its browser."""
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()


def run_in_child(
    run_id: uuid.UUID,
    worker_id: str,
    settings: Settings,
    command: list[str] | None = None,
) -> None:
    """Run one bot in a new process group, renewing the lease while it runs.

    The group is killed at the time limit, if the lease is lost, or if this worker is stopped.
    """
    command = command or [sys.executable, "-m", "botplatform.worker.child"]
    child = subprocess.Popen([*command, str(run_id)], start_new_session=True)
    time_limit = settings.run_time_limit_seconds
    deadline = time.monotonic() + time_limit
    outcome: tuple[Status, str, str] | None = None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                outcome = (
                    Status.TIMEOUT,
                    "run_time_limit",
                    f"The run exceeded the {time_limit} second limit",
                )
                break
            try:
                exit_code = child.wait(timeout=min(settings.lease_renew_seconds, remaining))
            except subprocess.TimeoutExpired:
                with SessionLocal.begin() as session:
                    owned = queue.renew(session, run_id, worker_id, settings.lease_seconds)
                if not owned:
                    log.warning("Lost the lease on run %s, killing its process", run_id)
                    return
                continue
            # This only takes effect if the child exited without recording a result.
            outcome = (
                Status.ERROR,
                "bot_process_died",
                f"The bot process exited with code {exit_code} without a result",
            )
            break
    except BaseException:
        # SIGTERM raises SystemExit here.
        kill_group(child)
        with SessionLocal.begin() as session:
            queue.finish(session, run_id, Status.ERROR, "worker_stopped", "The worker was stopped")
        raise
    finally:
        kill_group(child)
    with SessionLocal.begin() as session:
        queue.finish(session, run_id, *outcome)


def stop_on_sigterm() -> None:
    """Turn SIGTERM into SystemExit, so `run_in_child` can clean up before the worker exits."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    stop_on_sigterm()

    settings = Settings.model_validate({})
    worker_id = socket.gethostname()

    registry.validate(BOTS)
    with SessionLocal.begin() as session:
        registry.publish(session, BOTS)
    log.info("Worker %s published bots: %s", worker_id, [bot.id for bot in BOTS])

    while True:
        with SessionLocal.begin() as session:
            reaped = queue.reap_expired(session)
        if reaped:
            log.warning("Marked runs from lost workers as errors: %s", reaped)
        with SessionLocal.begin() as session:
            run = queue.claim_next(session, worker_id, settings.lease_seconds)
            run_id = run.id if run else None
        if run_id is None:
            time.sleep(settings.worker_poll_seconds)
            continue
        log.info("Starting run %s", run_id)
        run_in_child(run_id, worker_id, settings)
        log.info("Finished run %s", run_id)


if __name__ == "__main__":
    main()
