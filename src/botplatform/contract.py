"""The interface between the platform and bots. Bots import only this module from the core."""

from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol


class Status(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    BLOCKED = "blocked"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


ACTIVE_STATUSES = frozenset({Status.QUEUED, Status.RUNNING})

type FinalStatus = Literal[
    Status.SUCCESS, Status.BLOCKED, Status.FAILED, Status.TIMEOUT, Status.ERROR
]


@dataclass(frozen=True)
class BotResult:
    """A bot's final outcome. `reason` is a short code that the bot defines."""

    status: FinalStatus
    reason: str | None = None
    error: str | None = None


class RunContext(Protocol):
    """What the platform gives a bot for one run. Each call is saved immediately."""

    run_id: str

    def record_challenge_id(self, value: str) -> None:
        """Save a challenge ID as the run's latest, and keep it in the run's history."""

    def event(self, type: str, data: dict[str, Any] | None = None) -> None:
        """Add an entry to the run's timeline."""

    def artifact(self, name: str, content_type: str, data: bytes) -> None:
        """Attach a file to the run, such as a screenshot."""


class Bot[M: StrEnum](ABC):
    """Subclass this, construct it, and add the instance to `BOTS`.

    `BOTS` is in `botplatform/bots/__init__.py`. Each bot has its own enum of modes: pass the
    class as `modes`, and its members, in declared order, are the modes the UI offers.
    `watchable` lists the modes whose runs can be watched live.
    """

    def __init__(
        self,
        id: str,
        name: str,
        description: str = "",
        *,
        modes: type[M],
        watchable: Collection[M] = (),
    ) -> None:
        self.id = id
        self.name = name
        self.description = description
        self.modes = modes
        self.watchable = frozenset(watchable)

    def mode_names(self) -> list[str]:
        """The modes as the strings the platform stores, in declared order."""
        return [mode.value for mode in self.modes]

    @abstractmethod
    def run(self, ctx: RunContext, mode: M) -> BotResult:
        """Run once in `mode` and return the outcome. An uncaught exception is recorded as `error`."""
