"""The ARCaptcha bots: one `ArcaptchaBot` class, and an instance of it for each variant.

The variants differ in identity, browser profiles and what they do about a puzzle (their
`Challenge`). `run` checks the credentials, then `SeleniumBot` starts Chrome with the profile for
the run's mode and `steps` runs the flow: open and tick, let the challenge deal with a puzzle, log
in, judge. The registered instances are at the bottom: the baseline, one bot for each other
browser profile, and the solver bots.
"""

import os
from collections.abc import Mapping

from botplatform.bots.arcaptcha.challenge import Challenge, GiveUp
from botplatform.bots.arcaptcha.checkbox import open_and_tick, types
from botplatform.bots.arcaptcha.gap_finders import FINDERS
from botplatform.bots.arcaptcha.login import log_in
from botplatform.bots.arcaptcha.session import DEFAULT_TIMEOUTS, DEMO_URL, Session, StepTimeouts
from botplatform.bots.arcaptcha.slider_solver import SliderSolver
from botplatform.bots.utils.browser import (
    BrowserMode,
    BrowserSession,
    SeleniumBot,
    describe,
    screenshot,
)
from botplatform.bots.utils.drag import MOVERS
from botplatform.bots.utils.profiles import (
    ALL_SIGNALS,
    ALL_SIGNALS_HEADLESS,
    BASELINE,
    PROFILES,
    Profile,
)
from botplatform.contract import BotResult, RunContext, Status


def bot_id(profile_name: str) -> str:
    """The id of the registered bot that runs `profile_name`. The baseline keeps the plain id."""
    return "arcaptcha" if profile_name == "baseline" else f"arcaptcha-{profile_name}"


class ArcaptchaBot(SeleniumBot):
    """The ARCaptcha scenario. The arguments say which variant this instance is."""

    def __init__(
        self,
        id: str,
        name: str,
        description: str,
        *,
        profile: Profile = BASELINE,
        profile_by_mode: Mapping[BrowserMode, Profile] | None = None,
        challenge: Challenge | None = None,
        url: str = DEMO_URL,
        timeouts: StepTimeouts = DEFAULT_TIMEOUTS,
    ) -> None:
        super().__init__(id, name, description, profile=profile, profile_by_mode=profile_by_mode)
        self.challenge = challenge or GiveUp()  # give up on a puzzle unless told otherwise
        self.url = url
        self.timeouts = timeouts

    def run(self, ctx: RunContext, mode: BrowserMode) -> BotResult:
        if not os.environ.get("ARCAPTCHA_USERNAME") or not os.environ.get("ARCAPTCHA_PASSWORD"):
            return BotResult(
                Status.ERROR,
                "missing_credentials",
                "Set ARCAPTCHA_USERNAME and ARCAPTCHA_PASSWORD in .env",
            )
        return super().run(ctx, mode)

    def steps(self, browser: BrowserSession) -> BotResult:
        session = Session(
            browser.ctx,
            browser.driver,
            os.environ["ARCAPTCHA_USERNAME"],
            os.environ["ARCAPTCHA_PASSWORD"],
            self.url,
            self.timeouts,
        )
        earlier = open_and_tick(session)
        if (
            earlier
            and earlier.reason == "challenge_unsolved"
            and types(session.creates)[-1:] == ["puzzle"]
        ):
            earlier = self.challenge.resolve(session)
        screenshot(session, "after-click")
        # Decision 3b: the login is always attempted, but it can never upgrade an earlier failure.
        try:
            verdict = log_in(session)
        except Exception as error:
            if not earlier:
                raise
            session.ctx.event("login_failed", {"error": describe(error)})
            screenshot(session, "login-failed")
            return earlier
        screenshot(session, "after-login")
        # Both steps found nothing wrong, so this is the only place a run can succeed.
        if session.solved:
            return earlier or verdict or BotResult(Status.SUCCESS, "solved")
        return earlier or verdict or BotResult(Status.SUCCESS)


BASELINE_DESCRIPTION = (
    "Ticks the checkbox on demo.arcaptcha.co, records challenge_id, logs in and checks that "
    "the login really succeeded."
)


def profile_bot(profile: Profile) -> ArcaptchaBot:
    """The baseline scenario with `profile`, as bot `arcaptcha-<name>`.

    One bot per profile makes the run history the evidence: a bot's runs are one profile's runs.
    """
    return ArcaptchaBot(
        bot_id(profile.name),
        f"ARCaptcha demo (Selenium, {profile.name})",
        f"{BASELINE_DESCRIPTION} Browser profile: {profile.description}",
        profile=profile,
    )


def solver_bot(finder: str, mover: str) -> ArcaptchaBot:
    """An automatic solver bot, `arcaptcha-solver-<finder>-<mover>`.

    The finder and mover names are keys of `gap_finders.FINDERS` and `drag.MOVERS`.
    """
    return ArcaptchaBot(
        f"arcaptcha-solver-{finder}-{mover}",
        f"ARCaptcha demo (automatic solver: {finder} finder, {mover} movement)",
        (
            "An automatic solver. Ticks the checkbox and, when a puzzle appears, finds the gap "
            f"with the '{finder}' finder and drags the handle there with '{mover}' movement "
            "(Selenium ActionChains), up to 3 answers per run, then logs in. A verified login "
            "ends as success with the reason solved. If no gap is found the run ends as "
            "blocked / gap_not_found, and after 3 rejected answers as blocked / solve_failed. "
            "Headful uses the all-signals profile and headless the all-signals-headless one."
        ),
        profile=ALL_SIGNALS,
        profile_by_mode={
            BrowserMode.HEADFUL: ALL_SIGNALS,
            BrowserMode.HEADLESS: ALL_SIGNALS_HEADLESS,
        },
        challenge=SliderSolver(finder, mover),
    )


BASELINE_BOT = ArcaptchaBot("arcaptcha", "ARCaptcha demo (Selenium)", BASELINE_DESCRIPTION)

PROFILE_BOTS: list[ArcaptchaBot] = [
    profile_bot(p) for p in PROFILES.values() if p.name != BASELINE.name
]

# One bot for every finder and mover, so a new one cannot go without a bot.
SOLVER_BOTS: list[ArcaptchaBot] = [
    solver_bot(finder, mover) for finder in FINDERS for mover in MOVERS
]
