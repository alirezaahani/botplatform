"""The registered bots, the rules `validate` enforces, and what `publish` does with the list."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from botplatform.bots import BOTS
from botplatform.bots.arcaptcha import ArcaptchaBot
from botplatform.db import BotRecord, SessionLocal
from botplatform.profiles import PROFILES
from botplatform.worker.registry import publish, validate
from tests.conftest import stub_bot

ARC = ["headless", "headful"]


def test_the_registry_snapshot():
    assert [(bot.id, bot.name, bot.modes) for bot in BOTS] == [
        ("example", "Example bot", ["direct"]),
        ("arcaptcha", "ARCaptcha demo (Selenium)", ARC),
        ("arcaptcha-stealth-flags", "ARCaptcha demo (Selenium, stealth-flags)", ARC),
        ("arcaptcha-no-cdc", "ARCaptcha demo (Selenium, no-cdc)", ARC),
        ("arcaptcha-webgl-fix", "ARCaptcha demo (Selenium, webgl-fix)", ARC),
        ("arcaptcha-all-signals", "ARCaptcha demo (Selenium, all-signals)", ARC),
        (
            "arcaptcha-all-signals-headless",
            "ARCaptcha demo (Selenium, all-signals-headless)",
            ARC,
        ),
        (
            "arcaptcha-solver-cv-linear",
            "ARCaptcha demo (automatic solver: cv finder, linear movement)",
            ARC,
        ),
        (
            "arcaptcha-solver-cv-eased",
            "ARCaptcha demo (automatic solver: cv finder, eased movement)",
            ARC,
        ),
        (
            "arcaptcha-solver-silhouette-linear",
            "ARCaptcha demo (automatic solver: silhouette finder, linear movement)",
            ARC,
        ),
        (
            "arcaptcha-solver-silhouette-eased",
            "ARCaptcha demo (automatic solver: silhouette finder, eased movement)",
            ARC,
        ),
    ]


def test_validate_accepts_the_registry():
    validate(BOTS)


def test_validate_rejects_a_duplicate_id():
    with pytest.raises(ValueError, match="Duplicate bot id: a"):
        validate([stub_bot("a"), stub_bot("a")])


@pytest.mark.parametrize(
    ("modes", "message"),
    [((), "`modes`"), (("direct", "direct"), "mode twice")],
    ids=["no-modes", "a-mode-twice"],
)
def test_validate_rejects_bad_modes(modes, message):
    with pytest.raises(ValueError, match=message):
        validate([stub_bot("a", modes=modes)])


def test_every_profile_has_a_bot_that_runs_with_it():
    by_id = {bot.id: bot for bot in BOTS}
    for name, profile in PROFILES.items():
        bot = by_id["arcaptcha" if name == "baseline" else f"arcaptcha-{name}"]
        assert isinstance(bot, ArcaptchaBot)
        assert bot.spec.profile is profile


def test_modes_given_as_one_string_are_refused_not_split_into_letters():
    with pytest.raises(TypeError, match="modes"):
        stub_bot("a", modes="direct")


def test_a_bot_removed_from_the_list_is_marked_inactive_and_not_deleted(clean_db: sessionmaker):
    a, b = stub_bot("a"), stub_bot("b")
    with SessionLocal.begin() as session:
        publish(session, [a, b])
    with SessionLocal.begin() as session:
        publish(session, [b])
    with SessionLocal() as session:
        active = {r.id: r.active for r in session.scalars(select(BotRecord))}
    assert active == {"a": False, "b": True}
