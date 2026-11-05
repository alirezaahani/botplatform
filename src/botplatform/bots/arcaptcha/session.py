"""The state of one run, and the infrastructure every step needs."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from selenium import webdriver

from botplatform.bots.arcaptcha.js import BLANK_PASSWORD_JS
from botplatform.bots.arcaptcha.timeouts import (
    DEFAULT_TIMEOUTS,
    POLL_SECONDS,
    StepTimeout,
    StepTimeouts,
)
from botplatform.bots.selenium_support import (
    CapturedResponse,
    ResponseWatcher,
    call_handling_alerts,
)
from botplatform.contract import RunContext
from botplatform.profiles import BASELINE, Profile

if TYPE_CHECKING:
    from botplatform.bots.arcaptcha.puzzle import CapturedPuzzle

DEMO_URL = "https://demo.arcaptcha.co/"


def make_watcher(driver: webdriver.Chrome) -> ResponseWatcher:
    return ResponseWatcher(
        driver,
        {
            "create": lambda url: url.split("?")[0].endswith("/api/create"),
            "login": lambda url: url.split("?")[0].endswith("/api/login"),
            "answer": lambda url: url.split("?")[0].endswith("/arcaptcha/api/answer"),
        },
        # Not `login`, which holds the password. `create` carries the browser signals, and
        # `answer` is kept because nobody has seen a decoded one yet.
        capture_requests=frozenset({"create", "answer"}),
    )


@dataclass
class Session:
    """Everything one run knows. A plain holder: the steps are functions that take it."""

    ctx: RunContext
    driver: webdriver.Chrome
    username: str
    password: str
    url: str = DEMO_URL
    timeouts: StepTimeouts = DEFAULT_TIMEOUTS
    profile: Profile = BASELINE
    rng: random.Random = field(default_factory=random.Random)
    watcher: ResponseWatcher = field(init=False)

    creates: list[dict[str, Any]] = field(default_factory=list)  # decoded `create` answers
    logins: list[CapturedResponse] = field(default_factory=list)
    answer_records: list[dict[str, Any]] = field(default_factory=list)  # every `answer`, in order
    # When the latest `answer` arrived, unless a new `create` followed it.
    answered_at: float | None = None
    pending_puzzle: tuple[str | None] | None = None  # set by a `create`, taken by `drain`
    puzzles: int = 0  # puzzles seen so far, captured or not
    puzzle_srcs: list[str] = field(default_factory=list)  # image srcs already taken
    capture: CapturedPuzzle | None = None  # the current puzzle's bytes, if captured
    solved: bool = False  # the solver's answer was accepted

    def __post_init__(self) -> None:
        self.watcher = make_watcher(self.driver)


def do(session: Session, action: Callable[[], Any], *, retry: bool = True) -> Any:
    """Run any driver call. A JS `alert()` is recorded and dismissed instead of crashing it."""

    def on_alert(text: str) -> None:
        session.ctx.event("alert", {"text": text})

    return call_handling_alerts(session.driver, action, on_alert, retry=retry)


def wait_for(session: Session, check: Callable[[], Any], seconds: float, step: str) -> Any:
    deadline = time.monotonic() + seconds
    while True:
        result = do(session, check)
        if result:
            return result
        if time.monotonic() >= deadline:
            raise StepTimeout(step)
        time.sleep(POLL_SECONDS)


def screenshot(session: Session, name: str) -> None:
    def capture() -> None:
        session.driver.execute_script(BLANK_PASSWORD_JS)
        session.ctx.artifact(f"{name}.png", "image/png", session.driver.get_screenshot_as_png())

    try:
        do(session, capture)
    except Exception as error:  # noqa: BLE001 - a missing screenshot must not change the result
        session.ctx.event("screenshot_failed", {"name": name, "type": type(error).__name__})
