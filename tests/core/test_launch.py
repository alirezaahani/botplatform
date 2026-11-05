"""Launching a run from the web UI: only an active bot, in one of its modes, gets queued."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from botplatform.db import BotRecord, Run, SessionLocal
from botplatform.web.app import app


@pytest.fixture
def client(clean_db: sessionmaker) -> Iterator[TestClient]:
    with SessionLocal.begin() as session:
        session.add(BotRecord(id="solo", name="Solo", modes=["headless"]))
        session.add(BotRecord(id="retired", name="Retired", modes=["headless"], active=False))
    with TestClient(app) as test_client:
        yield test_client


def queued() -> list[tuple[str, str]]:
    with SessionLocal() as session:
        return [(run.bot_id, run.mode) for run in session.scalars(select(Run))]


def test_a_launch_queues_a_run_and_opens_its_page(client: TestClient):
    response = client.post("/bots/solo/runs", data={"mode": "headless"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/runs/")
    assert queued() == [("solo", "headless")]


@pytest.mark.parametrize(
    ("bot_id", "mode", "status_code", "message"),
    [
        ("missing", "headless", 404, "No active bot 'missing'"),
        ("retired", "headless", 404, "No active bot 'retired'"),
        ("solo", "headful", 400, "'solo' does not support mode 'headful'"),
    ],
    ids=["unknown-bot", "inactive-bot", "unsupported-mode"],
)
def test_a_refused_launch_says_why_and_queues_nothing(
    client: TestClient, bot_id: str, mode: str, status_code: int, message: str
):
    response = client.post(f"/bots/{bot_id}/runs", data={"mode": mode}, follow_redirects=False)

    assert response.status_code == status_code
    assert message in response.json()["detail"]
    assert queued() == []
