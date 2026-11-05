"""Capturing the puzzle's images and finding its handle."""

import base64
import time
from dataclasses import dataclass
from typing import Any

from selenium.webdriver.common.by import By

from botplatform.bots.arcaptcha.images import sniff_image
from botplatform.bots.arcaptcha.js import FETCH_IMAGES_JS, PUZZLE_INFO_JS
from botplatform.bots.arcaptcha.session import Session, do, wait_for
from botplatform.bots.arcaptcha.timeouts import StepTimeout
from botplatform.bots.selenium_support import describe
from botplatform.solver.movement import HANDLE


@dataclass
class CapturedPuzzle:
    """One puzzle's images as fetched in the page, and the piece's inline `top` in px."""

    n: int
    challenge_id: str | None
    background: bytes
    piece: bytes
    piece_top: int | None


def capture_puzzle(
    session: Session,
    challenge_id: str | None,
    *,
    n: int | None = None,
    seconds: float | None = None,
) -> None:
    """Save the puzzle's two images and its geometry. Any failure is recorded, never raised.

    The bytes are also kept in `session.capture` for the solver. A retry for the same puzzle
    passes its `n` and a longer `seconds`.
    """
    ctx, driver = session.ctx, session.driver
    if n is None:
        session.puzzles += 1
        n = session.puzzles
    try:
        info = wait_for(
            session,
            lambda: driver.execute_script(PUZZLE_INFO_JS, session.puzzle_srcs),
            session.timeouts.puzzle_images if seconds is None else seconds,
            "puzzle_images",
        )
        srcs = [info["background"]["src"], info["piece"]["src"]]
        session.puzzle_srcs.extend(srcs)
        fetched = do(session, lambda: driver.execute_async_script(FETCH_IMAGES_JS, *srcs))
        if not isinstance(fetched, dict) or "error" in fetched:
            raise RuntimeError((fetched or {}).get("error", "no result"))
        saved = {}
        raw: dict[str, bytes] = {}
        for part in ("background", "piece"):
            data = base64.b64decode(fetched[part]["b64"])
            raw[part] = data
            content_type, extension = sniff_image(data, fetched[part]["content_type"])
            name = f"puzzle-{n}-{part}.{extension}"
            ctx.artifact(name, content_type, data)
            saved[part] = name
        session.capture = CapturedPuzzle(
            n, challenge_id, raw["background"], raw["piece"], pixels(info["piece"])
        )
        ctx.event(
            "puzzle_captured", {"challenge_id": challenge_id, "n": n, "artifacts": saved, **info}
        )
    except Exception as error:  # noqa: BLE001 - a missing capture must not change the result
        ctx.event(
            "puzzle_capture_failed",
            {"challenge_id": challenge_id, "n": n, "error": describe(error)},
        )


def pixels(piece: dict[str, Any]) -> int | None:
    """The piece's inline `top` (like '60px') as a number, or None."""
    try:
        return round(float(str(piece.get("style_top", "")).removesuffix("px")))
    except ValueError:
        return None


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
        challenge_id = session.creates[-1]["challenge_id"]
        capture_puzzle(session, challenge_id, n=session.puzzles, seconds=remaining)
    return session.capture
