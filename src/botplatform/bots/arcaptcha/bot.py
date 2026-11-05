"""The ARCaptcha bots: one `ArcaptchaBot` class, built from a `BotSpec` for each variant.

A `BotSpec` says what differs between the bots: identity, modes, browser profiles and what to do
about a puzzle (its `Challenge`). `run` checks the credentials, then `SeleniumBot` starts Chrome
with the spec's profile for the run's mode and `steps` runs the flow: open and tick, let the
challenge deal with a puzzle, log in, judge. The registered instances are at the bottom: the
baseline, one bot for each other browser profile, and the solver bots.
"""

import os
from dataclasses import dataclass, field
from typing import Protocol

from botplatform.bots.arcaptcha.checkbox import open_and_tick, types
from botplatform.bots.arcaptcha.gap_finders import FINDERS
from botplatform.bots.arcaptcha.login import log_in
from botplatform.bots.arcaptcha.session import DEFAULT_TIMEOUTS, DEMO_URL, Session, StepTimeouts
from botplatform.bots.arcaptcha.slider_solver import SliderSolver
from botplatform.bots.utils.browser import BrowserSession, SeleniumBot, describe, screenshot
from botplatform.bots.utils.drag import MOVERS
from botplatform.bots.utils.profiles import (
    ALL_SIGNALS,
    ALL_SIGNALS_HEADLESS,
    BASELINE,
    PROFILES,
    Profile,
)
from botplatform.contract import BotResult, RunContext, Status


class Challenge(Protocol):
    """What a bot does when the widget shows a challenge it has to pass."""

    def resolve(self, session: Session) -> BotResult | None:
        """The latest `create` is a puzzle and was not accepted: try to deal with it.

        Return a final BotResult to end the challenge phase with that outcome (the login still
        runs after, but cannot upgrade it), or None if the challenge was passed.
        """
        ...


class GiveUp:
    """The default: do nothing, so the run ends as blocked / challenge_unsolved."""

    def resolve(self, session: Session) -> BotResult | None:
        return BotResult(Status.BLOCKED, "challenge_unsolved")


def bot_id(profile_name: str) -> str:
    """The id of the registered bot that runs `profile_name`. The baseline keeps the plain id."""
    return "arcaptcha" if profile_name == "baseline" else f"arcaptcha-{profile_name}"


@dataclass(frozen=True)
class BotSpec:
    id: str
    name: str
    description: str
    modes: tuple[str, ...]
    profile: Profile = BASELINE
    # A profile for a mode, where `profile` is not right for every mode. Not listed: `profile`.
    profile_by_mode: dict[str, Profile] = field(default_factory=dict)
    # What the bot does when the widget shows a puzzle. Give up unless the spec says otherwise.
    challenge: Challenge = field(default_factory=GiveUp)


BASELINE_SPEC = BotSpec(
    id="arcaptcha",
    name="ARCaptcha demo (Selenium)",
    description=(
        "Ticks the checkbox on demo.arcaptcha.co, records challenge_id, logs in and checks that "
        "the login really succeeded."
    ),
    modes=("headless", "headful"),
)


def solver_spec(finder: str, mover: str) -> BotSpec:
    """An automatic solver bot, `arcaptcha-solver-<finder>-<mover>`.

    The finder and mover names are keys of `gap_finders.FINDERS` and `drag.MOVERS`.
    """
    return BotSpec(
        id=f"arcaptcha-solver-{finder}-{mover}",
        name=f"ARCaptcha demo (automatic solver: {finder} finder, {mover} movement)",
        description=(
            "An automatic solver. Ticks the checkbox and, when a puzzle appears, finds the gap "
            f"with the '{finder}' finder and drags the handle there with '{mover}' movement "
            "(Selenium ActionChains), up to 3 answers per run, then logs in. A verified login "
            "ends as success with the reason solved. If no gap is found the run ends as "
            "blocked / gap_not_found, and after 3 rejected answers as blocked / solve_failed. "
            "Headful uses the all-signals profile and headless the all-signals-headless one."
        ),
        modes=("headless", "headful"),
        profile=ALL_SIGNALS,
        profile_by_mode={"headful": ALL_SIGNALS, "headless": ALL_SIGNALS_HEADLESS},
        challenge=SliderSolver(finder, mover),
    )


def profile_spec(profile: Profile) -> BotSpec:
    """The baseline scenario with `profile`, as bot `arcaptcha-<name>`.

    One bot per profile makes the run history the evidence: a bot's runs are one profile's runs.
    """
    return BotSpec(
        id=bot_id(profile.name),
        name=f"ARCaptcha demo (Selenium, {profile.name})",
        description=f"{BASELINE_SPEC.description} Browser profile: {profile.description}",
        modes=BASELINE_SPEC.modes,
        profile=profile,
    )


class ArcaptchaBot(SeleniumBot):
    """The ARCaptcha scenario. A `BotSpec` says which variant this instance is."""

    def __init__(
        self,
        spec: BotSpec,
        *,
        url: str = DEMO_URL,
        timeouts: StepTimeouts = DEFAULT_TIMEOUTS,
        profile: Profile | None = None,
    ) -> None:
        # A profile passed in wins over the spec's, for every mode.
        super().__init__(
            spec.id,
            spec.name,
            spec.description,
            spec.modes,
            profile=profile or spec.profile,
            profile_by_mode={} if profile else spec.profile_by_mode,
        )
        self.spec = spec
        self.url = url
        self.timeouts = timeouts

    def run(self, ctx: RunContext) -> BotResult:
        if not os.environ.get("ARCAPTCHA_USERNAME") or not os.environ.get("ARCAPTCHA_PASSWORD"):
            return BotResult(
                Status.ERROR,
                "missing_credentials",
                "Set ARCAPTCHA_USERNAME and ARCAPTCHA_PASSWORD in .env",
            )
        return super().run(ctx)

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
            earlier = self.spec.challenge.resolve(session)
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


BASELINE_BOT = ArcaptchaBot(BASELINE_SPEC)

PROFILE_BOTS: list[ArcaptchaBot] = [
    ArcaptchaBot(profile_spec(p)) for p in PROFILES.values() if p.name != BASELINE.name
]

# One bot for every finder and mover, so a new one cannot go without a bot.
SOLVER_BOTS: list[ArcaptchaBot] = [
    ArcaptchaBot(solver_spec(finder, mover)) for finder in FINDERS for mover in MOVERS
]
