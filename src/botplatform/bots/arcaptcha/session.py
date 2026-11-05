"""The state of one run, and the infrastructure every step needs."""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import NoAlertPresentException, UnexpectedAlertPresentException

from botplatform.bots.arcaptcha.timeouts import (
    DEFAULT_TIMEOUTS,
    POLL_SECONDS,
    StepTimeout,
    StepTimeouts,
)
from botplatform.bots.selenium_support import ResponseWatcher, describe
from botplatform.contract import RunContext
from botplatform.profiles import BASELINE, Profile

DEMO_URL = "https://demo.arcaptcha.co/"


def make_watcher(driver: webdriver.Chrome) -> ResponseWatcher:
    return ResponseWatcher(
        driver,
        {
            "create": lambda url: url.split("?")[0].endswith("/api/create"),
            "login": lambda url: url.split("?")[0].endswith("/api/login"),
            "answer": lambda url: url.split("?")[0].endswith("/arcaptcha/api/answer"),
        },
    )


@dataclass
class CapturedPuzzle:
    """One puzzle's images as fetched in the page, and the piece's inline `top` in px."""

    n: int
    challenge_id: str | None
    background: bytes
    piece: bytes
    piece_top: int | None


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
    logins: list[dict[str, Any]] = field(default_factory=list)  # every `login`, in order
    answer_records: list[dict[str, Any]] = field(default_factory=list)  # every `answer`, in order
    pending_puzzle: tuple[str | None] | None = None  # set by a `create`, taken by `drain`
    puzzles: int = 0  # puzzles seen so far, captured or not
    puzzle_srcs: list[str] = field(default_factory=list)  # image srcs already taken
    capture: CapturedPuzzle | None = None  # the current puzzle's bytes, if captured
    solved: bool = False  # the solver's answer was accepted

    def __post_init__(self) -> None:
        self.watcher = make_watcher(self.driver)


def do(session: Session, action: Callable[[], Any], *, retry: bool = True) -> Any:
    """Run any driver call, and deal with a JS `alert()` that interrupts it.

    By default Chrome dismisses the alert and the call raises `UnexpectedAlertPresentException`.
    This records the alert's text as an event, dismisses it if it is somehow still open, and
    then repeats the call. Pass `retry=False` for calls that must not run twice, such as a click:
    they return None after an alert.
    """
    for _ in range(5):
        try:
            return action()
        except UnexpectedAlertPresentException as alert:
            text = str(alert.alert_text or alert.msg or "")[:300]
            session.ctx.event("alert", {"text": text})
            try:
                session.driver.switch_to.alert.dismiss()
            except NoAlertPresentException:
                pass  # Chrome already dismissed it
            if not retry:
                return None
    return action()


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
        session.ctx.artifact(f"{name}.png", "image/png", session.driver.get_screenshot_as_png())

    try:
        do(session, capture)
    except Exception as error:  # noqa: BLE001 - a missing screenshot must not change the result
        session.ctx.event("screenshot_failed", {"name": name, "error": describe(error)})
