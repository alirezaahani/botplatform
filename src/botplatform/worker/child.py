"""Runs one bot in its own process, so the worker can kill it, along with its browser."""

import sys
import traceback
import uuid
from typing import Any

from sqlalchemy import update

from botplatform.bots import BOTS
from botplatform.contract import BotResult, Status
from botplatform.db import Run, RunArtifact, RunEvent, SessionLocal
from botplatform.worker.queue import finish


class DatabaseRunContext:
    """The `RunContext` given to bots. Each call commits, so it survives a kill or crash."""

    def __init__(self, run_id: uuid.UUID) -> None:
        self._run_id = run_id
        self.run_id = str(run_id)

    def record_challenge_id(self, value: str) -> None:
        with SessionLocal.begin() as session:
            session.add(RunEvent(run_id=self._run_id, type="challenge_id", data={"value": value}))
            session.execute(update(Run).where(Run.id == self._run_id).values(challenge_id=value))

    def event(self, type: str, data: dict[str, Any] | None = None) -> None:
        with SessionLocal.begin() as session:
            session.add(RunEvent(run_id=self._run_id, type=type, data=data))

    def artifact(self, name: str, content_type: str, data: bytes) -> None:
        with SessionLocal.begin() as session:
            session.add(
                RunArtifact(run_id=self._run_id, name=name, content_type=content_type, data=data)
            )


def execute(run_id: uuid.UUID) -> BotResult:
    with SessionLocal() as session:
        run = session.get_one(Run, run_id)
        bot_id, mode_name = run.bot_id, run.mode

    bot = next((bot for bot in BOTS if bot.id == bot_id), None)
    if bot is None:
        return BotResult(Status.ERROR, "bot_unavailable", f"This worker has no bot '{bot_id}'")
    try:
        mode = bot.modes(mode_name)
    except ValueError:
        return BotResult(Status.ERROR, "mode_unavailable", f"'{bot_id}' has no mode '{mode_name}'")

    try:
        return bot.run(DatabaseRunContext(run_id), mode)
    except Exception:  # noqa: BLE001 - any bot failure becomes an error result
        return BotResult(Status.ERROR, "unhandled_exception", traceback.format_exc())


def main() -> None:
    run_id = uuid.UUID(sys.argv[1])
    result = execute(run_id)
    with SessionLocal.begin() as session:
        finish(session, run_id, result.status, result.reason, result.error)


if __name__ == "__main__":
    main()
