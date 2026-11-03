"""Checks the registered bots and publishes them for the web container to read."""

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from botplatform.contract import Bot
from botplatform.db import BotRecord


def validate(bots: list[type[Bot]]) -> None:
    seen: set[str] = set()
    for bot in bots:
        for attribute in ("id", "name", "modes"):
            if not getattr(bot, attribute, None):
                raise ValueError(f"{bot.__name__} must define a non-empty `{attribute}`")
        if bot.id in seen:
            raise ValueError(f"Duplicate bot id: {bot.id}")
        if len(set(bot.modes)) != len(bot.modes):
            raise ValueError(f"{bot.__name__} declares a mode twice: {bot.modes}")
        seen.add(bot.id)


def publish(session: Session, bots: list[type[Bot]]) -> None:
    """Upsert every registered bot, and mark the rest inactive."""
    for bot in bots:
        values = {
            "name": bot.name,
            "description": bot.description,
            "modes": bot.modes,
            "active": True,
        }
        session.execute(
            insert(BotRecord)
            .values(id=bot.id, **values)
            .on_conflict_do_update(
                index_elements=[BotRecord.id], set_={**values, "updated_at": func.now()}
            )
        )
    session.execute(
        update(BotRecord)
        .where(BotRecord.id.not_in([bot.id for bot in bots]))
        .values(active=False)
    )
