"""The registered bots: the full list, and the wiring that must not be forgotten."""

from botplatform.bots import BOTS
from botplatform.bots.arcaptcha import ArcaptchaBot
from botplatform.bots.utils.profiles import PROFILES
from botplatform.worker.registry import validate

ARC = ["headless", "headful"]


def test_the_registry_snapshot():
    assert [(bot.id, bot.name, bot.mode_names()) for bot in BOTS] == [
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
            "arcaptcha-solver-halo-linear",
            "ARCaptcha demo (automatic solver: halo finder, linear movement)",
            ARC,
        ),
        (
            "arcaptcha-solver-halo-eased",
            "ARCaptcha demo (automatic solver: halo finder, eased movement)",
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


def test_every_profile_has_a_bot_that_runs_with_it():
    by_id = {bot.id: bot for bot in BOTS}
    for name, profile in PROFILES.items():
        bot = by_id["arcaptcha" if name == "baseline" else f"arcaptcha-{name}"]
        assert isinstance(bot, ArcaptchaBot)
        assert bot.profile is profile
