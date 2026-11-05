"""The rules `validate` enforces and what `publish` does with the list, with stub bots."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from botplatform.db import BotRecord, SessionLocal
from botplatform.worker.registry import publish, validate
from tests.conftest import stub_bot


def test_validate_rejects_a_duplicate_id():
    with pytest.raises(ValueError, match="Duplicate bot id: a"):
        validate([stub_bot("a"), stub_bot("a")])


def test_a_bot_removed_from_the_list_is_marked_inactive_and_not_deleted(clean_db: sessionmaker):
    a, b = stub_bot("a"), stub_bot("b")
    with SessionLocal.begin() as session:
        publish(session, [a, b])
    with SessionLocal.begin() as session:
        publish(session, [b])
    with SessionLocal() as session:
        active = {r.id: r.active for r in session.scalars(select(BotRecord))}
    assert active == {"a": False, "b": True}
