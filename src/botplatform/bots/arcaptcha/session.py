"""The state of one run, the step time limits and the infrastructure every step needs."""

import random
from dataclasses import dataclass, field
from typing import Any

from selenium import webdriver

from botplatform.bots.utils.browser import BrowserSession
from botplatform.bots.utils.network import ResponseWatcher, path_endswith

DEMO_URL = "https://demo.arcaptcha.co/"


@dataclass(frozen=True)
class StepTimeouts:
    """Seconds allowed for each step. The defaults stay well below the run time limit."""

    load_page: float = 30
    find_checkbox: float = 15
    create_response: float = 20
    more_create_responses: float = 2
    login_response: float = 15
    toast: float = 5
    # A rejected answer brings a new puzzle quickly, so if no `create` follows an `answer` within
    # `answer_settle`, the solver takes the puzzle as finished.
    answer_settle: float = 3
    # How long a captured puzzle's two images get to load after its `create` arrives.
    puzzle_images: float = 5
    # Only for the automatic solver. `puzzle_ready` is how long a puzzle's handle and images get
    # to appear (the first puzzle's images came late live). A run makes at most `solve_attempts`
    # answers; a handle that did not move at all is pressed again on the same puzzle up to
    # `stuck_retries` times, and that does not count as an attempt.
    puzzle_ready: float = 20
    solve_attempts: int = 3
    stuck_retries: int = 2


DEFAULT_TIMEOUTS = StepTimeouts()


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
    puzzle_pending: bool = False  # the latest `create` is a puzzle that `drain` has to capture
    puzzles: int = 0  # puzzles seen so far, captured or not
    puzzle_srcs: list[str] = field(default_factory=list)  # image srcs already taken
    capture: CapturedPuzzle | None = None  # the current puzzle's bytes, if captured
    solved: bool = False  # the solver's answer was accepted

    def __post_init__(self) -> None:
        self.watcher = make_watcher(self.driver)
