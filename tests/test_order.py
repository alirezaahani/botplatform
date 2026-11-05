"""Newest bot first: the Bots page, the Stats page and the positions that publish records."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from botplatform.db import BotRecord, SessionLocal
from botplatform.web.app import app
from botplatform.worker import registry
from tests.conftest import stub_bot
from tests.test_stats_page import seed_run, stats_rows


@pytest.fixture
def client(clean_db: sessionmaker) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def add_bots(*positions: tuple[str, int]) -> None:
    with SessionLocal.begin() as session:
        for bot_id, position in positions:
            session.add(
                BotRecord(id=bot_id, name=bot_id, modes=["headless", "headful"], position=position)
            )


def order(text: str, names: list[str]) -> list[str]:
    return sorted(names, key=text.index)


def test_publish_sets_the_position_and_updates_it(client: TestClient):
    a, b, c = stub_bot("a"), stub_bot("b"), stub_bot("c")
    with SessionLocal.begin() as session:
        registry.publish(session, [a, b, c])
    with SessionLocal.begin() as session:
        registry.publish(session, [b, c])  # a is removed, b and c move up
    with SessionLocal.begin() as session:
        records = {r.id: r for r in session.scalars(select(BotRecord))}
    assert {k: (r.position, r.active) for k, r in records.items()} == {
        "a": (0, False),  # keeps its last position
        "b": (0, True),
        "c": (1, True),
    }


def test_bots_page_is_newest_first_with_ties_by_name(client: TestClient):
    add_bots(("old", 0), ("zeta", 2), ("alpha", 2), ("mid", 1))
    text = client.get("/bots").text
    assert order(text, ["old", "zeta", "alpha", "mid"]) == ["alpha", "zeta", "mid", "old"]


def test_stats_page_lists_the_newest_bot_first_and_headless_before_headful(client: TestClient):
    add_bots(("old", 0), ("new", 1))
    for bot in ("old", "new"):
        for mode in ("headful", "headless"):
            seed_run(bot=bot, mode=mode)
    assert list(stats_rows(client)) == [
        ("new", "headless"),
        ("new", "headful"),
        ("old", "headless"),
        ("old", "headful"),
    ]
