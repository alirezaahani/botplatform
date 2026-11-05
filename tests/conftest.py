"""Shared setup: a recording `RunContext`, the Chrome test marker, a display and the database."""

import os
import subprocess
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from botplatform.contract import Bot, BotResult
from botplatform.db import Base, BotRecord, Run, SessionLocal, engine

# Fixtures that start Chrome, or serve a page to it. A test using one is a Chrome test.
CHROME_FIXTURES = {"fake", "driver", "local_page"}


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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test that drives Chrome, so `-m browser` and `-m 'not browser'` split the suite."""
    for item in items:
        if CHROME_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.browser)


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
    assert xvfb.poll() is None, f"Xvfb did not start on :{number}"
    monkeypatch.setenv("DISPLAY", f":{number}")
    yield
    xvfb.terminate()
    xvfb.wait()


@pytest.fixture
def clean_db() -> Iterator[sessionmaker]:
    """A session factory on a database with no runs and no bots."""
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as session:
        session.execute(delete(Run))
        session.execute(delete(BotRecord))
    yield SessionLocal


@pytest.fixture
def db(clean_db: sessionmaker) -> sessionmaker:
    """The clean database with one bot published."""
    with clean_db.begin() as session:
        session.add(BotRecord(id="arcaptcha", name="ARCaptcha", modes=["headless"]))
    return clean_db


class StubBot(Bot):
    def run(self, ctx: Any) -> BotResult:
        raise NotImplementedError


def stub_bot(bot_id: str, modes: Sequence[str] = ("direct",)) -> Bot:
    """A bot that exists only to be registered."""
    return StubBot(bot_id, bot_id, modes=modes)
