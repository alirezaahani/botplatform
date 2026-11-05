"""The ARCaptcha bot: one class that runs the flow for whichever `BotSpec` it is built from.

`run` checks the credentials, then `SeleniumBot` starts Chrome with the spec's profile for the run's
mode and `steps` hands a `Session` to `run_flow`. The registered instances are at the bottom: the baseline, one bot
for each other browser profile, and the solver bots.
"""

import os

from botplatform.bots.arcaptcha.flow import run_flow
from botplatform.bots.arcaptcha.session import DEMO_URL, Session
from botplatform.bots.arcaptcha.spec import BASELINE_SPEC, BotSpec, profile_spec, solver_spec
from botplatform.bots.arcaptcha.timeouts import DEFAULT_TIMEOUTS, StepTimeouts
from botplatform.bots.utils.browser import BrowserSession, SeleniumBot
from botplatform.bots.utils.profiles import BASELINE, PROFILES, Profile
from botplatform.contract import BotResult, RunContext, Status


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
        return run_flow(session, self.spec.challenge)


BASELINE_BOT = ArcaptchaBot(BASELINE_SPEC)

PROFILE_BOTS: list[ArcaptchaBot] = [
    ArcaptchaBot(profile_spec(p)) for p in PROFILES.values() if p.name != BASELINE.name
]

SOLVER_BOTS: list[ArcaptchaBot] = [
    ArcaptchaBot(solver_spec("halo", "linear")),
    ArcaptchaBot(solver_spec("halo", "eased")),
    ArcaptchaBot(solver_spec("silhouette", "linear")),
    ArcaptchaBot(solver_spec("silhouette", "eased")),
]
