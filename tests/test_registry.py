"""The registered bots, and the rules `validate` enforces. No Chrome and no database."""

import pytest

from botplatform.bots import BOTS
from botplatform.worker.registry import validate
from tests.test_order import make_bot

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
        validate([make_bot("a"), make_bot("a")])


def test_validate_rejects_empty_modes():
    bot = make_bot("a")
    bot.modes = []
    with pytest.raises(ValueError, match="`modes`"):
        validate([bot])


def test_validate_rejects_a_duplicate_mode():
    bot = make_bot("a")
    bot.modes = ["direct", "direct"]
    with pytest.raises(ValueError, match="mode twice"):
        validate([bot])
