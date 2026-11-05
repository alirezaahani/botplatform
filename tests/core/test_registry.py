"""What `publish` does with the registered bots, with stub bots."""

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from botplatform.db import BotRecord, SessionLocal
from botplatform.worker.registry import publish
from tests.conftest import stub_bot


def test_a_bot_removed_from_the_list_is_marked_inactive_and_not_deleted(clean_db: sessionmaker):
    a, b = stub_bot("a"), stub_bot("b")
    with SessionLocal.begin() as session:
        publish(session, {"a": a, "b": b})
    with SessionLocal.begin() as session:
        publish(session, {"b": b})
    with SessionLocal() as session:
        active = {r.id: r.active for r in session.scalars(select(BotRecord))}
    assert active == {"a": False, "b": True}
