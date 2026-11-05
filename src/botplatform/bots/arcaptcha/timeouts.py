"""Step time limits and the error for running out of one."""

from dataclasses import dataclass


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


class StepTimeout(Exception):
    """A step ran out of time. `step` becomes the run's reason."""

    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step
