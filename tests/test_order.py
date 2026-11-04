"""Newest bot first: the Bots page, the Bonus report and the positions that publish records."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from botplatform.bots import BOTS
from botplatform.contract import Bot
from botplatform.db import Base, BotRecord, Run, session_factory
from botplatform.web.app import app
from botplatform.worker import registry
from tests.test_bonus import seed_run


def make_bot(bot_id: str) -> type[Bot]:
    return type(bot_id, (Bot,), {"id": bot_id, "name": bot_id, "modes": ["direct"]})


@pytest.fixture
def client() -> Iterator[TestClient]:
    sessions = session_factory()
    Base.metadata.create_all(sessions.kw["bind"])
    with sessions.begin() as session:
        session.execute(delete(Run))
        session.execute(delete(BotRecord))
    with TestClient(app) as test_client:
        yield test_client


def add_bots(*positions: tuple[str, int]) -> None:
    with session_factory().begin() as session:
        for bot_id, position in positions:
            session.add(
                BotRecord(id=bot_id, name=bot_id, modes=["headless", "headful"], position=position)
            )


def order(text: str, names: list[str]) -> list[str]:
    return sorted(names, key=text.index)


def test_the_registry_lists_bots_in_the_order_they_were_added():
    assert [bot.id for bot in BOTS] == [
        "example",
        "arcaptcha",
        "arcaptcha-stealth-flags",
        "arcaptcha-no-cdc",
        "arcaptcha-webgl-fix",
        "arcaptcha-all-signals",
        "arcaptcha-all-signals-headless",
        "arcaptcha-assisted",
        "arcaptcha-drag-probe",
    ]


def test_publish_sets_the_position_and_updates_it(client: TestClient):
    a, b, c = make_bot("a"), make_bot("b"), make_bot("c")
    sessions = session_factory()
    with sessions.begin() as session:
        registry.publish(session, [a, b, c])
    with sessions.begin() as session:
        registry.publish(session, [b, c])  # a is removed, b and c move up
    with sessions.begin() as session:
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


def test_bonus_page_and_markdown_follow_the_same_order(client: TestClient):
    add_bots(("old", 0), ("new", 1))
    for bot in ("old", "new"):
        for mode in ("headful", "headless"):
            seed_run(bot=bot, mode=mode)
    md = client.get("/bonus.md").text
    rows = [line.split("|")[1:3] for line in md.splitlines() if line.startswith(("| old", "| new"))]
    assert [(a.strip(), b.strip()) for a, b in rows] == [
        ("new", "headless"),
        ("new", "headful"),
        ("old", "headless"),
        ("old", "headful"),
    ]
    page = client.get("/bonus").text
    assert page.index("bot=new") < page.index("bot=old")
    assert md.index("| new | headless") < md.index("| old | headless")
