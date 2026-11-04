"""The bonus report page and its Markdown export, from seeded runs and events."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from botplatform.db import Base, BotRecord, Run, RunEvent, session_factory
from botplatform.stats import wilson_interval
from botplatform.web.app import app

OLD = datetime(2026, 11, 1, tzinfo=UTC)
NEW = datetime(2026, 11, 4, tzinfo=UTC)


def seed_run(
    bot: str = "arcaptcha",
    mode: str = "headless",
    captcha_type: str | None = "block",
    status: str = "blocked",
    reason: str | None = "captcha_blocked",
    challenge_id: str | None = "cid",
    viewer: bool = False,
    queued_at: datetime = NEW,
    answers: int = 1,
) -> None:
    with session_factory().begin() as session:
        run = Run(
            id=uuid.uuid4(), bot_id=bot, mode=mode, status=status, reason=reason,
            challenge_id=challenge_id, queued_at=queued_at,
        )  # fmt: skip
        session.add(run)
        session.flush()
        if captcha_type is not None or answers == 0:
            for _ in range(answers):
                session.add(
                    RunEvent(
                        run_id=run.id, type="create_response", data={"captcha_type": captcha_type}
                    )
                )
        if viewer:
            session.add(RunEvent(run_id=run.id, type="viewer_connected"))


@pytest.fixture
def client() -> Iterator[TestClient]:
    sessions = session_factory()
    Base.metadata.create_all(sessions.kw["bind"])
    with sessions.begin() as session:
        session.execute(delete(Run))
        session.execute(delete(BotRecord))
        for bot in ("arcaptcha", "arcaptcha-no-cdc"):
            session.add(BotRecord(id=bot, name=bot, modes=["headless", "headful"]))
    with TestClient(app) as test_client:
        yield test_client


def seed_mixed() -> None:
    for _ in range(3):
        seed_run()  # blocked
    seed_run(captcha_type="puzzle", status="failed", reason="no_slider_solver")
    seed_run(captcha_type="accept", status="success", reason=None)
    seed_run(captcha_type=None, status="error", reason="x", challenge_id=None)  # no create answer
    seed_run(viewer=True, captcha_type="puzzle")  # a person helped
    seed_run(bot="arcaptcha-no-cdc", captcha_type="puzzle", status="failed", reason="r")
    seed_run(bot="arcaptcha-no-cdc", mode="headful", captcha_type="block")
    seed_run(captcha_type="block", queued_at=OLD)


def test_page_counts_per_bot_and_mode(client: TestClient):
    seed_mixed()
    text = client.get("/bonus").text
    assert "/bonus.md" in text
    assert "1 excluded" in text
    md = client.get("/bonus.md").text
    row = next(line for line in md.splitlines() if line.startswith("| arcaptcha | headless"))
    low, high = wilson_interval(2, 6)
    assert "| 7 |" in row  # 3 + 1 + 1 + 1 + the old one: viewer run excluded
    assert "block 4, puzzle 1, accept 1, none 1" in row
    assert "| 2 of 6 |" in row
    assert f"33% ({low * 100:.0f}% to {high * 100:.0f}%)" in row
    assert "| 6 | 1 | 1 |" in row  # with challenge id, success, excluded


def test_viewer_runs_are_excluded_but_counted(client: TestClient):
    seed_run(viewer=True, captcha_type="puzzle")
    seed_run()
    md = client.get("/bonus.md").text
    assert "1 excluded (arcaptcha headless 1)" in md
    row = next(line for line in md.splitlines() if line.startswith("| arcaptcha | headless"))
    assert "| 1 | blocked/captcha_blocked 1 |" in row and "| 0 of 1 |" in row


def test_only_the_first_create_response_counts(client: TestClient):
    seed_run(captcha_type="block", answers=3)
    md = client.get("/bonus.md").text
    assert "block 1" in md


def test_filters_by_since_and_bot(client: TestClient):
    seed_mixed()
    since = client.get("/bonus.md", params={"since": "2026-11-03"}).text
    assert "since 2026-11-03T00:00:00+00:00" in since
    row = next(line for line in since.splitlines() if line.startswith("| arcaptcha | headless"))
    assert "| 6 |" in row  # the old run is gone
    only = client.get("/bonus.md", params={"bot": "arcaptcha-no-cdc"}).text
    assert "bot arcaptcha-no-cdc" in only
    assert "| arcaptcha | " not in only and "| arcaptcha-no-cdc | headful" in only
    assert client.get("/bonus", params={"since": "garbage"}).status_code == 400


def test_markdown_header_states_what_is_included(client: TestClient):
    seed_run()
    response = client.get("/bonus.md")
    assert response.headers["content-type"].startswith("text/markdown")
    for needle in ("Generated at:", "Filters:", "Every recorded run", '"Not blocked"', "Wilson"):
        assert needle in response.text


def test_empty_history_still_renders(client: TestClient):
    assert "No runs" in client.get("/bonus").text
    assert "No runs." in client.get("/bonus.md").text
