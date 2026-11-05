"""The slider solver: find the gap, drag the handle there, judge by the next puzzle."""

import time
from dataclasses import asdict, dataclass
from typing import Any

from selenium.webdriver.common.by import By

from botplatform.bots.arcaptcha import gap_finders
from botplatform.bots.arcaptcha.challenge import Challenge
from botplatform.bots.arcaptcha.checkbox import classify, types
from botplatform.bots.arcaptcha.puzzle_capture import capture_puzzle
from botplatform.bots.arcaptcha.responses import drain
from botplatform.bots.arcaptcha.session import CapturedPuzzle, Session
from botplatform.bots.utils import drag
from botplatform.bots.utils.browser import POLL_SECONDS, StepTimeout, describe, do, wait_for
from botplatform.contract import BotResult, Status

# The widget being dragged: the slider's handle and the puzzle piece it moves.
HANDLE = "div.draggable"
PIECE = "img.puzzle"
# The handle's and piece's `left` right now, in px (None when missing).
LEFTS_JS = """
const left = (selector) => {
  const el = document.querySelector(selector);
  return el ? parseFloat(getComputedStyle(el).left) : null;
};
return {handle: left(arguments[0]), piece: left(arguments[1])};
"""


@dataclass(kw_only=True)
class Attempt:
    """One try at one puzzle, as the `solve_attempt` event shows it (fields in event order)."""

    n: int
    puzzle: int
    challenge_id: str | None
    finder: str
    target_x: int | None = None
    mover: str
    dx: int | None = None
    duration: float | None = None
    steps: int | None = None
    stuck_retries: int = 0
    outcome: str | None = None
    handle_left: float | None = None
    piece_left: float | None = None
    message: str | None = None  # only when the finder found no gap
    error: str | None = None  # only when the drag raised

    def as_event(self) -> dict[str, Any]:
        event = asdict(self)
        for key in ("message", "error"):
            if event[key] is None:
                del event[key]
        return event


@dataclass(frozen=True)
class SliderSolver(Challenge):
    """Find the gap with a finder, drag the handle there with a mover, up to `solve_attempts` times.

    The answer's body never decides the outcome beyond this: an answer followed by no new puzzle
    within `answer_settle` is taken as accepted, and the login is the judge. `resolve` returns
    None for that, so the login runs. The names are keys of `gap_finders.FINDERS` and `drag.MOVERS`.
    """

    finder_name: str
    mover_name: str

    def resolve(self, session: Session) -> BotResult | None:
        ctx, timeouts = session.ctx, session.timeouts
        ctx.event(
            "solve_started",
            {
                "finder": self.finder_name,
                "mover": self.mover_name,
                "attempts": timeouts.solve_attempts,
                "stuck_retries": timeouts.stuck_retries,
                "puzzle_ready": timeouts.puzzle_ready,
            },
        )
        attempts = 0
        try:
            while attempts < timeouts.solve_attempts:
                do(session, lambda: drain(session))
                if types(session.creates)[-1:] != ["puzzle"]:
                    ctx.event("solve_finished", {"reason": "not_a_puzzle", "attempts": attempts})
                    return classify(session)
                attempts += 1
                result, accepted = self._attempt(session, attempts)
                if result is not None:
                    ctx.event("solve_finished", {"reason": "gap_not_found", "attempts": attempts})
                    return result
                if accepted:
                    session.solved = True
                    ctx.event("solve_finished", {"reason": "solved", "attempts": attempts})
                    return None
        except StepTimeout as timeout:
            ctx.event("solve_finished", {"reason": timeout.step})
            raise
        ctx.event("solve_finished", {"reason": "solve_failed", "attempts": attempts})
        return BotResult(Status.BLOCKED, "solve_failed")

    def _attempt(self, session: Session, n: int) -> tuple[BotResult | None, bool]:
        """One attempt on the current puzzle: (a final result or None, whether it was accepted)."""
        current = puzzle_ready(session)
        attempt = Attempt(
            n=n,
            puzzle=current.n,
            challenge_id=current.challenge_id,
            finder=self.finder_name,
            mover=self.mover_name,
        )
        try:
            target = gap_finders.FINDERS[self.finder_name](
                current.background, current.piece, current.piece_top or 0
            )
        except gap_finders.GapNotFound as error:
            attempt.outcome = "gap_not_found"
            attempt.message = str(error)[:200]
            session.ctx.event("solve_attempt", attempt.as_event())
            return BotResult(Status.BLOCKED, "gap_not_found"), False
        attempt.target_x = attempt.dx = target
        answers_before = len(session.answer_records)
        self._drag_with_retries(session, attempt, target)
        attempt.outcome = await_next_puzzle(session, current.n, answers_before)
        session.ctx.event("solve_attempt", attempt.as_event())
        return None, attempt.outcome == "accepted"

    def _drag_with_retries(self, session: Session, attempt: Attempt, target: int) -> None:
        """Drag the handle to `target`, again if it did not move. A failed drag is recorded."""
        result = None

        def snapshot() -> dict[str, float | None]:  # the script always returns both keys
            return do(session, lambda: session.driver.execute_script(LEFTS_JS, HANDLE, PIECE))

        try:
            while True:
                path = drag.MOVERS[self.mover_name](target, session.rng)
                attempt.duration = round(drag.duration(path), 3)
                attempt.steps = len(path)
                result = drag.perform_drag(
                    session.driver,
                    handle(session),
                    path,
                    snapshot,
                    lambda lefts: (lefts.get("handle") or 0) > 0,
                    lambda action: do(session, action),
                )
                if result.moved or attempt.stuck_retries >= session.timeouts.stuck_retries:
                    break
                attempt.stuck_retries += 1
                drag.release_everything(session.driver)
        except Exception as error:  # noqa: BLE001 - one failed drag must not stop the run
            attempt.error = describe(error)
            drag.release_everything(session.driver)
        if result is not None:
            attempt.handle_left = result.final.get("handle")
            attempt.piece_left = result.final.get("piece")


def await_next_puzzle(session: Session, n: int, answers_before: int) -> str:
    """Drain until the answer and then the next puzzle's capture arrive (or time runs out).

    Returns "rejected" if a new puzzle came, "accepted" if none did within `answer_settle` (the
    login is the judge), and "no_answer" if the answer request never appeared.
    """
    settle = session.timeouts.answer_settle
    deadline = time.monotonic() + settle
    while len(session.answer_records) == answers_before:
        if time.monotonic() >= deadline:
            return "no_answer"
        do(session, lambda: drain(session))
        time.sleep(POLL_SECONDS)
    deadline = time.monotonic() + settle
    while session.puzzles == n:
        if time.monotonic() >= deadline:
            return "accepted"
        do(session, lambda: drain(session))
        time.sleep(POLL_SECONDS)
    return "rejected"


def handle(session: Session) -> Any:
    """The slider handle once it is on screen, or StepTimeout."""
    found = wait_for(
        session,
        lambda: [
            e for e in session.driver.find_elements(By.CSS_SELECTOR, HANDLE) if e.is_displayed()
        ],
        session.timeouts.puzzle_ready,
        "puzzle_ready",
    )
    return found[0]


def puzzle_ready(session: Session) -> CapturedPuzzle:
    """The current puzzle with its handle on screen and its images in hand, or StepTimeout."""
    deadline = time.monotonic() + session.timeouts.puzzle_ready
    handle(session)
    while session.capture is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or session.puzzles == 0:
            raise StepTimeout("puzzle_ready")
        challenge_id = session.creates[-1].challenge_id
        capture_puzzle(session, challenge_id, n=session.puzzles, seconds=remaining)
    return session.capture
