"""Publishes the registered bots for the web container to read."""

from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from botplatform.contract import Bot
from botplatform.db import BotRecord


def publish(session: Session, bots: dict[str, Bot[Any]]) -> None:
    """Upsert every registered bot, and mark the rest inactive.

    Removed bots keep their last `position`, so they stay in place in the history.
    """
    for position, bot in enumerate(bots.values()):
        values = {
            "name": bot.name,
            "description": bot.description,
            "modes": bot.mode_names(),
            "watchable_modes": [mode.value for mode in bot.watchable],
            "active": True,
            "position": position,
        }
        session.execute(
            insert(BotRecord)
            .values(id=bot.id, **values)
            .on_conflict_do_update(
                index_elements=[BotRecord.id], set_={**values, "updated_at": func.now()}
            )
        )
    session.execute(update(BotRecord).where(BotRecord.id.not_in(list(bots))).values(active=False))
