import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from botplatform.bots.arcaptcha import BASELINE_SPEC, ArcaptchaBot, StepTimeouts
from botplatform.contract import BotResult
from botplatform.db import Base, BotRecord, Run, session_factory
from tests.fake_demo.server import FakeDemo

USERNAME = "tester@example.com"
PASSWORD = "s3cret-Pass-9431"
# Short, so the suite stays quick. Chrome itself takes a few seconds to start.
FAST = StepTimeouts(
    load_page=3,
    find_checkbox=2,
    create_response=3,
    more_create_responses=1,
    login_response=3,
    toast=1.5,
)


class RecordingContext:
    """A `RunContext` that keeps everything in memory."""

    run_id = "test-run"
    mode = "headless"

    def __init__(self, on_artifact: Callable[[str], None] | None = None) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.challenge_ids: list[str] = []
        self.artifacts: list[tuple[str, str, bytes]] = []
        self._on_artifact = on_artifact

    def record_challenge_id(self, value: str) -> None:
        self.challenge_ids.append(value)

    def event(self, type: str, data: dict[str, Any] | None = None) -> None:
        self.events.append((type, data or {}))

    def artifact(self, name: str, content_type: str, data: bytes) -> None:
        if self._on_artifact:
            self._on_artifact(name)
        self.artifacts.append((name, content_type, data))

    def of(self, type: str) -> list[dict[str, Any]]:
        return [data for kind, data in self.events if kind == type]

    def one(self, type: str) -> dict[str, Any]:
        found = self.of(type)
        assert len(found) == 1, f"expected one '{type}' event, got {found}"
        return found[0]


@dataclass
class Outcome:
    result: BotResult
    ctx: RecordingContext
    seconds: float


def assert_no_password(outcome: Outcome) -> None:
    """The password must not appear in events, artifact names, the reason or the error text."""
    everything = repr(outcome.ctx.events) + repr([a[0] for a in outcome.ctx.artifacts])
    everything += f"{outcome.result.reason} {outcome.result.error}"
    assert PASSWORD not in everything


@pytest.fixture
def fake() -> Iterator[FakeDemo]:
    demo = FakeDemo()
    demo.start()
    yield demo
    demo.stop()


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCAPTCHA_USERNAME", USERNAME)
    monkeypatch.setenv("ARCAPTCHA_PASSWORD", PASSWORD)


@pytest.fixture
def run_bot(fake: FakeDemo, credentials: None) -> Callable[..., Outcome]:
    """Run the real bot with real Chrome against the fake. Every run checks for the password."""

    def run(url: str | None = None, timeouts: StepTimeouts = FAST) -> Outcome:
        ctx = RecordingContext()
        started = time.monotonic()
        result = ArcaptchaBot(BASELINE_SPEC, url=url or fake.url, timeouts=timeouts).run(ctx)
        outcome = Outcome(result, ctx, time.monotonic() - started)
        assert_no_password(outcome)
        return outcome

    return run


@pytest.fixture
def db() -> Iterator[sessionmaker]:
    """A session factory on an empty database with one bot published."""
    sessions = session_factory()
    Base.metadata.create_all(sessions.kw["bind"])
    with sessions.begin() as session:
        session.execute(delete(Run))
        session.execute(delete(BotRecord))
        session.add(BotRecord(id="arcaptcha", name="ARCaptcha", modes=["headless"]))
    yield sessions
