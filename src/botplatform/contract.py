"""The interface between the platform and bots. Bots import only this module from the core."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Protocol


class Status(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    BLOCKED = "blocked"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


ACTIVE_STATUSES = frozenset({Status.QUEUED, Status.RUNNING})


@dataclass(frozen=True)
class BotResult:
    """A bot's final outcome. `reason` is a short code that the bot defines."""

    status: Status
    reason: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status in ACTIVE_STATUSES:
            raise ValueError(f"{self.status} is not a final status")


class RunContext(Protocol):
    """What the platform gives a bot for one run. Each call is saved immediately."""

    run_id: str
    mode: str

    def record_challenge_id(self, value: str) -> None:
        """Save a challenge ID as the run's latest, and keep it in the run's history."""

    def event(self, type: str, data: dict[str, Any] | None = None) -> None:
        """Add an entry to the run's timeline. Never include passwords or other secrets."""

    def artifact(self, name: str, content_type: str, data: bytes) -> None:
        """Attach a file to the run, such as a screenshot."""


class Bot(ABC):
    """Subclass this and add the class to `BOTS` in `botplatform/bots/__init__.py`."""

    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    modes: ClassVar[list[str]]

    @abstractmethod
    def run(self, ctx: RunContext) -> BotResult:
        """Run once and return the outcome. An uncaught exception is recorded as `error`."""
