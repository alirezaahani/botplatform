"""The ARCaptcha demo bot: tick the checkbox, read `challenge_id`, log in, verify the result.

Puzzle capture (data for a future slider solver): when a `create` of type `puzzle` arrives and its
two images are on screen, the run saves them as artifacts `puzzle-<n>-background.<ext>` and
`puzzle-<n>-piece.<ext>` and records a `puzzle_captured` event (n counts puzzles in the run from 1).
Events are appended in order, so the `answer_request` events that follow a `puzzle_captured`
event, up to the next one, belong to puzzle n; the `answer` record itself is unchanged. A failed
capture records `puzzle_capture_failed` and never changes the run's result.
"""

import os
import traceback
from typing import ClassVar
from urllib.parse import urlsplit

from botplatform.bots.arcaptcha.flow import run_flow
from botplatform.bots.arcaptcha.redaction import redact
from botplatform.bots.arcaptcha.session import DEMO_URL, Session
from botplatform.bots.arcaptcha.timeouts import DEFAULT_TIMEOUTS, StepTimeouts
from botplatform.bots.selenium_support import chrome
from botplatform.contract import Bot, BotResult, RunContext, Status
from botplatform.profiles import (
    ALL_SIGNALS,
    ALL_SIGNALS_HEADLESS,
    BASELINE,
    PROFILES,
    Profile,
    bot_id,
)


class ArcaptchaBot(Bot):
    id = "arcaptcha"
    name = "ARCaptcha demo (Selenium)"
    description = (
        "Ticks the checkbox on demo.arcaptcha.co, records challenge_id, logs in and checks that "
        "the login really succeeded."
    )
    modes: ClassVar[list[str]] = ["headless", "headful"]
    profile: ClassVar[Profile] = BASELINE
    # A profile for a mode, where `profile` is not right for every mode. Not listed: `profile`.
    profile_by_mode: ClassVar[dict[str, Profile]] = {}
    solve_with: ClassVar[tuple[str, str] | None] = None  # (finder name, mover name)

    def __init__(
        self,
        url: str = DEMO_URL,
        timeouts: StepTimeouts = DEFAULT_TIMEOUTS,
        profile: Profile | None = None,
    ) -> None:
        self.url = url
        self.timeouts = timeouts
        self.profile = profile or type(self).profile
        self._given_profile = profile  # a profile passed in wins over the one for the mode

    def profile_for(self, mode: str) -> Profile:
        """The browser profile for `mode`: the one passed in, else the class's for that mode."""
        return self._given_profile or type(self).profile_by_mode.get(mode, self.profile)

    def run(self, ctx: RunContext) -> BotResult:
        username = os.environ.get("ARCAPTCHA_USERNAME")
        password = os.environ.get("ARCAPTCHA_PASSWORD")
        if not username or not password:
            return BotResult(
                Status.ERROR,
                "missing_credentials",
                "Set ARCAPTCHA_USERNAME and ARCAPTCHA_PASSWORD in .env",
            )
        try:
            profile = self.profile_for(ctx.mode)
            with chrome(headless=ctx.mode == "headless", profile=profile) as driver:
                session = Session(ctx, driver, username, password, self.url, self.timeouts, profile)
                return run_flow(session, self.solve_with)
        except Exception:  # noqa: BLE001 - every failure becomes an error result
            # The password must never reach the run's error field, whatever the exception says.
            host = urlsplit(self.url).hostname or ""
            details = redact(traceback.format_exc(), password, host)
            return BotResult(Status.ERROR, "unhandled_exception", details)


def solver_bot(finder: str, mover: str) -> type[ArcaptchaBot]:
    """An automatic solver bot, `arcaptcha-solver-<finder>-<mover>`.

    The finder and mover names are keys of `gap.FINDERS` and `movement.MOVERS`.
    """
    return type(
        f"ArcaptchaSolver{finder.title()}{mover.title()}Bot",
        (ArcaptchaBot,),
        {
            "id": f"arcaptcha-solver-{finder}-{mover}",
            "name": f"ARCaptcha demo (automatic solver: {finder} finder, {mover} movement)",
            "description": (
                "An automatic solver. Ticks the checkbox and, when a puzzle appears, finds the gap "
                f"with the '{finder}' finder and drags the handle there with '{mover}' movement "
                "(Selenium ActionChains), up to 3 answers per run, then logs in. A verified login "
                "ends as success with the reason solved. If no gap is found the run ends as "
                "blocked / gap_not_found, and after 3 rejected answers as blocked / solve_failed. "
                "Headful uses the all-signals profile and headless the all-signals-headless one."
            ),
            "modes": ["headless", "headful"],
            "profile": ALL_SIGNALS,
            "profile_by_mode": {"headful": ALL_SIGNALS, "headless": ALL_SIGNALS_HEADLESS},
            "solve_with": (finder, mover),
        },
    )


SOLVER_BOTS: list[type[ArcaptchaBot]] = [
    solver_bot("cv", "linear"),
    solver_bot("cv", "eased"),
    solver_bot("silhouette", "linear"),
    solver_bot("silhouette", "eased"),
]


def profile_bot(profile: Profile) -> type[ArcaptchaBot]:
    """A bot class that runs the ARCaptcha scenario with `profile`, as `arcaptcha-<name>`.

    One bot per profile makes the run history the evidence: a bot's runs are one profile's runs.
    """
    return type(
        "Arcaptcha" + profile.name.title().replace("-", "") + "Bot",
        (ArcaptchaBot,),
        {
            "id": bot_id(profile.name),
            "name": f"ARCaptcha demo (Selenium, {profile.name})",
            "description": f"{ArcaptchaBot.description} Browser profile: {profile.description}",
            "profile": profile,
        },
    )


# The baseline is `ArcaptchaBot` itself, so its id, name and description stay as they were.
PROFILE_BOTS: list[type[ArcaptchaBot]] = [
    profile_bot(p) for p in PROFILES.values() if p.name != BASELINE.name
]
