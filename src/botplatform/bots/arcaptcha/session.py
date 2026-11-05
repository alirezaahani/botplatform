"""The state of one run, and the infrastructure every step needs."""

import random
from dataclasses import dataclass, field
from typing import Any

from selenium import webdriver

from botplatform.bots.arcaptcha.timeouts import DEFAULT_TIMEOUTS, StepTimeouts
from botplatform.bots.utils.browser import BrowserSession
from botplatform.bots.utils.network import ResponseWatcher, path_endswith

DEMO_URL = "https://demo.arcaptcha.co/"


def make_watcher(driver: webdriver.Chrome) -> ResponseWatcher:
    return ResponseWatcher(
        driver,
        {
            "create": path_endswith("/api/create"),
            "login": path_endswith("/api/login"),
            "answer": path_endswith("/arcaptcha/api/answer"),
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
class Session(BrowserSession):
    """Everything one run knows. A plain holder: the steps are functions that take it."""

    username: str
    password: str
    url: str = DEMO_URL
    timeouts: StepTimeouts = DEFAULT_TIMEOUTS
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
