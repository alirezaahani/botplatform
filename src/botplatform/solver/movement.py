"""Moving the handle: pure path generators and one executor.

A path is a list of points `(x_offset, y_offset, pause_seconds)`: offsets from the handle's
centre where the press happened, and the time to wait after reaching the point. The last point
has `x_offset == dx`. Generators take a `random.Random` so tests can seed them.
"""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from selenium.webdriver.common.action_chains import ActionChains

from botplatform.bots.arcaptcha.js import HANDLE, PIECE

Path = list[tuple[int, int, float]]

LINEAR_STEPS = 8
LINEAR_SECONDS = 0.6
EASED_STEPS = (25, 40)
EASED_SECONDS = (0.8, 1.5)
EASED_WOBBLE = (1, 2)  # the largest vertical offset, in px, is one of these


def linear_path(dx: int, rng: random.Random | None = None) -> Path:
    """8 equal steps at an equal pace (the shape that was accepted live). `rng` is unused."""
    pause = LINEAR_SECONDS / LINEAR_STEPS
    return [(round(dx * i / LINEAR_STEPS), 0, pause) for i in range(1, LINEAR_STEPS + 1)]


def eased_path(dx: int, rng: random.Random) -> Path:
    """Fast at first, slowing toward the end (ease-out cubic), with a small vertical wobble.

    25-40 steps over 0.8-1.5 s. x never goes backwards and never passes `dx`, and the last
    point is exactly `dx` with no vertical offset.
    """
    steps = rng.randint(*EASED_STEPS)
    total = rng.uniform(*EASED_SECONDS)
    wobble = rng.randint(*EASED_WOBBLE)
    weights = [rng.uniform(0.7, 1.3) for _ in range(steps)]
    scale = total / sum(weights)
    path: Path = []
    for i in range(1, steps + 1):
        t = i / steps
        x = dx if i == steps else round(dx * (1 - (1 - t) ** 3))
        y = 0 if i == steps else rng.randint(-wobble, wobble)
        path.append((x, y, weights[i - 1] * scale))
    return path


def duration(path: Path) -> float:
    return sum(pause for _, _, pause in path)


MOVERS: dict[str, Callable[[int, random.Random], Path]] = {
    "linear": linear_path,
    "eased": eased_path,
}

# The handle's and piece's `left` right now, in px (None when missing).
LEFTS_JS = """
const left = (selector) => {
  const el = document.querySelector(selector);
  return el ? parseFloat(getComputedStyle(el).left) : null;
};
return {handle: left(arguments[0]), piece: left(arguments[1])};
"""
# After the first step the handle must have left 0, or the widget ignored the press.
MOVED_WAIT = 0.4


@dataclass
class DragResult:
    moved: bool  # the handle left 0 after the first step
    handle_left: float | None  # just before the release
    piece_left: float | None


def perform_drag(
    driver: Any, handle: Any, path: Path, do: Callable[[Callable[[], Any]], Any] = lambda f: f()
) -> DragResult:
    """Press the handle's centre, follow `path`, release: one motion with the pointer held.

    After the first step that moves right it reads the handle's position. If the handle did not
    move it releases and returns `moved=False` without finishing the path. `do` wraps every
    driver call (the scenario passes its alert-handling wrapper).
    """
    do(
        lambda: driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'})", handle
        )
    )
    # Duration 0: the path's pauses set the pace, not Selenium's default 250 ms per move.
    actions = ActionChains(driver, duration=0)

    def run() -> None:
        do(actions.perform)
        # Clear only the local queue: clearing the remote end would release the button.
        for device in actions.w3c_actions.devices:
            device.clear_actions()

    def lefts() -> dict[str, Any]:
        return do(lambda: driver.execute_script(LEFTS_JS, HANDLE, PIECE)) or {}

    x = y = 0
    actions.move_to_element(handle).click_and_hold()
    first = next((i for i, point in enumerate(path) if point[0] > 0), None)
    head = path[: first + 1] if first is not None else path
    for px, py, pause in head:
        actions.move_by_offset(px - x, py - y)
        x, y = px, py
        actions.pause(pause)
    run()
    moved = True
    if first is not None:
        deadline = time.monotonic() + MOVED_WAIT
        while True:
            moved = (lefts().get("handle") or 0) > 0
            if moved or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
    if not moved:
        actions.release()
        run()
        return DragResult(False, lefts().get("handle"), lefts().get("piece"))
    for px, py, pause in path[len(head) :]:
        actions.move_by_offset(px - x, py - y)
        x, y = px, py
        actions.pause(pause)
    run()
    final = lefts()
    actions.release()
    run()
    return DragResult(True, final.get("handle"), final.get("piece"))
