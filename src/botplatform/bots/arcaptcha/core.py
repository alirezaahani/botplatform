"""The ARCaptcha bot: one class that runs the flow for whichever `BotSpec` it is built from.

`run` reads the credentials, starts Chrome with the spec's profile for the run's mode, and hands a
`Session` to `run_flow`. Exceptions propagate to the worker, which turns them into an
`unhandled_exception` result. The registered instances are at the bottom: the baseline, one bot
for each other browser profile, and the solver bots.
"""

import os

from botplatform.bots.arcaptcha.flow import run_flow
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
        profile = self.profile_for(ctx.mode)
        with chrome(headless=ctx.mode == "headless", profile=profile) as driver:
            session = Session(ctx, driver, username, password, self.url, self.timeouts, profile)
            return run_flow(session, self.spec.challenge)


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
