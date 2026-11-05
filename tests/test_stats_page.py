"""The stats page and the run history columns, from seeded runs and events."""

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from botplatform.db import BotRecord, Run, RunEvent, SessionLocal
from botplatform.stats import wilson_interval
from botplatform.web.app import app

START = datetime(2026, 11, 4, 9, 0, 0, tzinfo=UTC)


def seed_run(
    bot: str = "arcaptcha",
    mode: str = "headless",
    status: str = "success",
    viewer: bool = False,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> uuid.UUID:
    with SessionLocal.begin() as session:
        run = Run(
            id=uuid.uuid4(), bot_id=bot, mode=mode, status=status, queued_at=START,
            started_at=started_at, ended_at=ended_at,
        )  # fmt: skip
        session.add(run)
        session.flush()
        if viewer:
            session.add(RunEvent(run_id=run.id, type="viewer_connected"))
        return run.id


@pytest.fixture
def client(clean_db: sessionmaker) -> Iterator[TestClient]:
    with clean_db.begin() as session:
        for bot in ("arcaptcha", "other"):
            session.add(BotRecord(id=bot, name=bot, modes=["headless", "headful"]))
    with TestClient(app) as test_client:
        yield test_client


def stats_rows(client: TestClient) -> dict[tuple[str, str], list[str]]:
    """Each table row of /stats as its cells, keyed by (bot, mode)."""
    html = client.get("/stats").text
    rows = {}
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL):
        cells = [c.strip() for c in re.findall(r"<td>(.*?)</td>", row, re.DOTALL)]
        if cells:
            rows[(cells[0], cells[1])] = cells[2:]
    return rows


def test_counts_per_bot_and_mode_with_rate_and_interval(client: TestClient):
    for status in ["success"] * 6 + ["blocked"] * 2 + ["failed", "timeout", "error"]:
        seed_run(status=status)
    seed_run(bot="other", mode="headful", status="success")
    rows = stats_rows(client)
    low, high = wilson_interval(6, 11)
    rate = f"55% ({low * 100:.0f}% to {high * 100:.0f}%)"
    # Runs, Success, Blocked, Failed, Timeout, Error, rate, Watched
    assert rows[("arcaptcha", "headless")] == ["11", "6", "2", "1", "1", "1", rate, "0"]
    assert rows[("other", "headful")][:2] == ["1", "1"]
    assert set(rows) == {("arcaptcha", "headless"), ("other", "headful")}


def test_a_perfect_count_is_not_shown_as_a_certain_hundred_percent(client: TestClient):
    for _ in range(80):
        seed_run()
    rate = stats_rows(client)[("arcaptcha", "headless")][6]
    assert rate.startswith("100% (") and "(100% to" not in rate


def test_watched_runs_are_left_out_of_the_rate_and_counted_as_watched(client: TestClient):
    seed_run(status="success")
    seed_run(status="blocked")
    seed_run(status="success", viewer=True)
    seed_run(status="success", viewer=True)
    row = stats_rows(client)[("arcaptcha", "headless")]
    assert row[0:3] == ["2", "1", "1"]  # Runs, Success, Blocked
    assert row[6].startswith("50% (")
    assert row[7] == "2"


def test_queued_and_running_runs_are_not_counted_anywhere(client: TestClient):
    seed_run(status="success")
    seed_run(status="queued")
    seed_run(status="running")
    seed_run(bot="other", status="running", viewer=True)
    rows = stats_rows(client)
    assert rows[("arcaptcha", "headless")][0] == "1"
    assert ("other", "headless") not in rows


def test_a_bot_with_only_watched_runs_shows_a_dash_for_the_rate(client: TestClient):
    seed_run(viewer=True)
    row = stats_rows(client)[("arcaptcha", "headless")]
    assert row[0] == "0" and row[6] == "-" and row[7] == "1"


def test_runs_of_a_bot_that_is_no_longer_active_still_show(client: TestClient):
    with SessionLocal.begin() as session:
        session.get_one(BotRecord, "other").active = False
    seed_run(bot="other")
    assert ("other", "headless") in stats_rows(client)


def test_empty_history_renders_and_the_page_explains_its_rules(client: TestClient):
    response = client.get("/stats")
    assert response.status_code == 200
    assert "No finished runs" in response.text
    assert "viewer_connected" in response.text
    assert client.get("/bonus").status_code == 404


def test_history_shows_start_end_and_duration_and_blanks_when_missing(client: TestClient):
    done = seed_run(started_at=START + timedelta(seconds=5), ended_at=START + timedelta(seconds=47))
    never_started = seed_run(status="queued")
    text = client.get("/runs").text
    finished_row = next(r for r in text.split("<tr>") if str(done)[:8] in r)
    assert "2026-11-04 09:00:05" in finished_row
    assert "2026-11-04 09:00:47" in finished_row
    assert "42s" in finished_row
    queued_row = next(r for r in text.split("<tr>") if str(never_started)[:8] in r)
    assert "None" not in queued_row
    assert re.findall(r"<td>(.*?)</td>", queued_row, re.DOTALL)[-3:] == ["", "", ""]
