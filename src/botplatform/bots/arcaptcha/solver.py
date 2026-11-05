"""The automatic solver: find the gap, drag the handle there, judge by the next puzzle."""

import time
from typing import Any

from selenium.webdriver.common.action_chains import ActionChains

from botplatform.bots.arcaptcha import puzzle
from botplatform.bots.arcaptcha.errors import describe
from botplatform.bots.arcaptcha.session import Session, do
from botplatform.bots.arcaptcha.timeouts import POLL_SECONDS, StepTimeout
from botplatform.bots.arcaptcha.traffic import classify, drain, types
from botplatform.contract import BotResult, Status
from botplatform.solver import gap, movement


def run_solver(session: Session, solve_with: tuple[str, str]) -> BotResult | None:
    """Solve the puzzle: find the gap, drag the handle there, up to `solve_attempts` times.

    The answer's body never decides the outcome beyond this: an
    answer followed by no new puzzle within `answer_settle` is taken as accepted, and the
    login is the judge. Returns None for that, so the login runs.
    """
    timeouts = session.timeouts
    finder_name, mover_name = solve_with
    session.ctx.event(
        "solve_started",
        {
            "finder": finder_name,
            "mover": mover_name,
            "attempts": timeouts.solve_attempts,
            "stuck_retries": timeouts.stuck_retries,
            "puzzle_ready": timeouts.puzzle_ready,
        },
    )
    try:
        result = solve_loop(session, finder_name, mover_name)
    except StepTimeout as timeout:
        session.ctx.event("solve_finished", {"reason": timeout.step})
        raise
    return result


def solve_loop(session: Session, finder_name: str, mover_name: str) -> BotResult | None:
    timeouts, ctx = session.timeouts, session.ctx
    attempts = 0
    while attempts < timeouts.solve_attempts:
        do(session, lambda: drain(session))
        if types(session.creates)[-1:] != ["puzzle"]:
            ctx.event("solve_finished", {"reason": "not_a_puzzle", "attempts": attempts})
            return classify(session)
        current = puzzle.puzzle_ready(session)
        attempts += 1
        attempt: dict[str, Any] = {
            "n": attempts,
            "puzzle": current.n,
            "challenge_id": current.challenge_id,
            "finder": finder_name,
            "target_x": None,
            "mover": mover_name,
            "dx": None,
            "duration": None,
            "steps": None,
            "stuck_retries": 0,
            "outcome": None,
            "handle_left": None,
            "piece_left": None,
        }
        try:
            target = gap.FINDERS[finder_name](
                current.background, current.piece, current.piece_top or 0
            )
        except gap.GapNotFound as error:
            attempt["outcome"] = "gap_not_found"
            attempt["message"] = str(error)[:200]
            ctx.event("solve_attempt", attempt)
            ctx.event("solve_finished", {"reason": "gap_not_found", "attempts": attempts})
            return BotResult(Status.BLOCKED, "gap_not_found")
        attempt["target_x"] = target
        attempt["dx"] = target
        answers_before = len(session.answer_records)
        drag = None
        try:
            while True:
                path = movement.MOVERS[mover_name](target, session.rng)
                attempt["duration"] = round(movement.duration(path), 3)
                attempt["steps"] = len(path)
                handle = puzzle.handle(session)
                drag = movement.perform_drag(
                    session.driver, handle, path, lambda action: do(session, action)
                )
                if drag.moved or attempt["stuck_retries"] >= timeouts.stuck_retries:
                    break
                attempt["stuck_retries"] += 1
                release_everything(session)
        except Exception as error:  # noqa: BLE001 - one failed drag must not stop the run
            attempt["error"] = describe(error)
            release_everything(session)
        if drag is not None:
            attempt["handle_left"] = drag.handle_left
            attempt["piece_left"] = drag.piece_left
        outcome = await_next_puzzle(session, current.n, answers_before)
        attempt["outcome"] = {
            "next_puzzle": "rejected",
            "no_new_puzzle": "accepted",
            "no_answer": "no_answer",
        }[outcome]
        ctx.event("solve_attempt", attempt)
        if attempt["outcome"] == "accepted":
            session.solved = True
            ctx.event("solve_finished", {"reason": "solved", "attempts": attempts})
            return None
    ctx.event("solve_finished", {"reason": "solve_failed", "attempts": attempts})
    return BotResult(Status.BLOCKED, "solve_failed")


def release_everything(session: Session) -> None:
    """After a failed drag, let go of the mouse so the next attempt starts clean."""
    try:
        ActionChains(session.driver).reset_actions()
        session.driver.execute_cdp_cmd(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": 0, "y": 0, "button": "left", "clickCount": 1},
        )
    except Exception:  # noqa: BLE001, S110 - best effort only
        pass


def await_next_puzzle(session: Session, n: int, answers_before: int) -> str:
    """Drain until the answer and then the next puzzle's capture arrive (or time runs out)."""
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
            return "no_new_puzzle"
        do(session, lambda: drain(session))
        time.sleep(POLL_SECONDS)
    return "next_puzzle"
