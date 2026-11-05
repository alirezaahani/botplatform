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
from urllib.parse import urlsplit

from botplatform.bots.arcaptcha.flow import run_flow
from botplatform.bots.arcaptcha.redaction import redact
from botplatform.bots.arcaptcha.session import DEMO_URL, Session
from botplatform.bots.arcaptcha.spec import BASELINE_SPEC, BotSpec, profile_spec, solver_spec
from botplatform.bots.arcaptcha.timeouts import DEFAULT_TIMEOUTS, StepTimeouts
from botplatform.bots.selenium_support import chrome
from botplatform.contract import Bot, BotResult, RunContext, Status
from botplatform.profiles import BASELINE, PROFILES, Profile


class ArcaptchaBot(Bot):
    """The ARCaptcha scenario. A `BotSpec` says which variant this instance is."""

    def __init__(
        self,
        spec: BotSpec,
        *,
        url: str = DEMO_URL,
        timeouts: StepTimeouts = DEFAULT_TIMEOUTS,
        profile: Profile | None = None,
    ) -> None:
        super().__init__(spec.id, spec.name, spec.description, spec.modes)
        self.spec = spec
        self.url = url
        self.timeouts = timeouts
        self.profile = profile or spec.profile
        self._given_profile = profile  # a profile passed in wins over the one for the mode

    def profile_for(self, mode: str) -> Profile:
        """The browser profile for `mode`: the one passed in, else the spec's for that mode."""
        return self._given_profile or self.spec.profile_by_mode.get(mode, self.spec.profile)

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
                return run_flow(session, self.spec.solve_with)
        except Exception:  # noqa: BLE001 - every failure becomes an error result
            # The password must never reach the run's error field, whatever the exception says.
            host = urlsplit(self.url).hostname or ""
            details = redact(traceback.format_exc(), password, host)
            return BotResult(Status.ERROR, "unhandled_exception", details)


BASELINE_BOT = ArcaptchaBot(BASELINE_SPEC)

PROFILE_BOTS: list[ArcaptchaBot] = [
    ArcaptchaBot(profile_spec(p)) for p in PROFILES.values() if p.name != BASELINE.name
]

SOLVER_BOTS: list[ArcaptchaBot] = [
    ArcaptchaBot(solver_spec("cv", "linear")),
    ArcaptchaBot(solver_spec("cv", "eased")),
    ArcaptchaBot(solver_spec("silhouette", "linear")),
    ArcaptchaBot(solver_spec("silhouette", "eased")),
]
