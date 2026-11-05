"""The ARCaptcha bots' setup: the fake demo site and one way to run a registered bot."""

import copy
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest

from botplatform.bots import BOTS
from botplatform.bots.arcaptcha import ArcaptchaBot, StepTimeouts
from botplatform.bots.utils.browser import BrowserMode
from botplatform.bots.utils.profiles import Profile
from botplatform.contract import BotResult, Status
from tests.bots.arcaptcha.fake_demo.server import FakeDemo
from tests.conftest import RecordingContext

USERNAME = "tester@example.com"
PASSWORD = "s3cret-Pass-9431"
# Short, so the suite stays quick. Chrome itself takes a few seconds to start.
FAST = StepTimeouts(
    load_page=3,
    find_checkbox=2,
    create_response=3,
    more_create_responses=1,
    login_response=3,
    toast=1.5,
)


@dataclass
class Outcome:
    """A finished run: what the bot returned, what it recorded, and how long it took."""

    result: BotResult
    ctx: RecordingContext
    seconds: float

    @property
    def verdict(self) -> tuple[Status, str | None]:
        return self.result.status, self.result.reason


@pytest.fixture
def fake() -> Iterator[FakeDemo]:
    demo = FakeDemo()
    demo.start()
    yield demo
    demo.stop()


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCAPTCHA_USERNAME", USERNAME)
    monkeypatch.setenv("ARCAPTCHA_PASSWORD", PASSWORD)


@pytest.fixture
def run_bot(fake: FakeDemo, credentials: None) -> Callable[..., Outcome]:
    """Run a registered ARCaptcha bot with real Chrome against the fake."""

    def run(
        bot_id: str = "arcaptcha",
        *,
        url: str | None = None,
        timeouts: StepTimeouts = FAST,
        profile: Profile | None = None,
    ) -> Outcome:
        registered = next(bot for bot in BOTS if bot.id == bot_id)
        assert isinstance(registered, ArcaptchaBot)
        bot = copy.copy(registered)
        bot.url, bot.timeouts = url or fake.url, timeouts
        if profile:  # a profile passed in wins for every mode
            bot.profile, bot.profile_by_mode = profile, {}
        ctx = RecordingContext()
        started = time.monotonic()
        result = bot.run(ctx, BrowserMode.HEADLESS)
        outcome = Outcome(result, ctx, time.monotonic() - started)
        return outcome

    return run
