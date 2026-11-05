"""Shared setup: the fake demo site, a recording `RunContext`, and one way to run a bot."""

import os
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from botplatform.bots import BOTS
from botplatform.bots.arcaptcha import ArcaptchaBot, StepTimeouts
from botplatform.contract import Bot, BotResult, Status
from botplatform.db import Base, BotRecord, Run, session_factory
from botplatform.profiles import Profile
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
    """A finished run: what the bot returned, what it recorded, and how long it took."""

    result: BotResult
    ctx: RecordingContext
    seconds: float

    @property
    def verdict(self) -> tuple[Status, str | None]:
        return self.result.status, self.result.reason

    def assert_no_password(self) -> None:
        """The password must not be in events, artifact names, the reason or the error text."""
        everything = repr(self.ctx.events) + repr([a[0] for a in self.ctx.artifacts])
        everything += f"{self.result.reason} {self.result.error}"
        assert PASSWORD not in everything


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test that drives Chrome, so `-m browser` and `-m 'not browser'` split the suite."""
    for item in items:
        if "fake" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.browser)


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
    """Run a registered ARCaptcha bot with real Chrome against the fake, and check for leaks."""

    def run(
        bot_id: str = "arcaptcha",
        *,
        url: str | None = None,
        timeouts: StepTimeouts = FAST,
        profile: Profile | None = None,
    ) -> Outcome:
        registered = next(bot for bot in BOTS if bot.id == bot_id)
        assert isinstance(registered, ArcaptchaBot)
        bot = ArcaptchaBot(registered.spec, url=url or fake.url, timeouts=timeouts, profile=profile)
        ctx = RecordingContext()
        started = time.monotonic()
        result = bot.run(ctx)
        outcome = Outcome(result, ctx, time.monotonic() - started)
        outcome.assert_no_password()
        return outcome

    return run


@pytest.fixture
def display(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A virtual display for headful Chrome, on a number of its own for each test process."""
    number = 100 + os.getpid() % 800
    xvfb = subprocess.Popen(
        ["Xvfb", f":{number}", "-screen", "0", "1280x800x24", "-nolisten", "tcp"]
    )
    for _ in range(50):
        if Path(f"/tmp/.X11-unix/X{number}").exists():
            break
        time.sleep(0.1)
    monkeypatch.setenv("DISPLAY", f":{number}")
    yield
    xvfb.terminate()
    xvfb.wait()


@pytest.fixture
def clean_db() -> Iterator[sessionmaker]:
    """A session factory on a database with no runs and no bots."""
    sessions = session_factory()
    Base.metadata.create_all(sessions.kw["bind"])
    with sessions.begin() as session:
        session.execute(delete(Run))
        session.execute(delete(BotRecord))
    yield sessions


@pytest.fixture
def db(clean_db: sessionmaker) -> sessionmaker:
    """The clean database with one bot published."""
    with clean_db.begin() as session:
        session.add(BotRecord(id="arcaptcha", name="ARCaptcha", modes=["headless"]))
    return clean_db


class StubBot(Bot):
    def run(self, ctx: Any) -> BotResult:
        raise NotImplementedError


def stub_bot(bot_id: str, modes: tuple[str, ...] = ("direct",)) -> Bot:
    """A bot that exists only to be registered."""
    return StubBot(bot_id, bot_id, modes=modes)
