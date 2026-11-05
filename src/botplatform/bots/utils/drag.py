"""Dragging a widget: pure path generators and one executor. The platform core never imports it.

A path is a list of points `(x_offset, y_offset, pause_seconds)`: offsets from the handle's
centre where the press happened, and the time to wait after reaching the point. The last point
has `x_offset == dx`. Generators take a `random.Random` so tests can seed them.
"""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.remote.webelement import WebElement

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

# After the first step that moves right, the widget must respond, or it ignored the press.
MOVED_WAIT = 0.4


@dataclass
class DragResult:
    moved: bool  # the widget responded after the first step
    final: dict[str, Any]  # the snapshot just before the release (after it, if it did not move)


def perform_drag(
    driver: webdriver.Chrome,
    handle: WebElement,
    path: Path,
    snapshot: Callable[[], dict[str, Any]],
    moved: Callable[[dict[str, Any]], bool],
    do: Callable[[Callable[[], Any]], Any] = lambda f: f(),
) -> DragResult:
    """Press the handle's centre, follow `path`, release: one motion with the pointer held.

    After the first step that moves right it calls `snapshot` (it reads the page state) until
    `moved(snapshot)` says the widget responded, for up to `MOVED_WAIT`. If it did not respond it
    releases and returns `moved=False` without finishing the path. `do` wraps every driver call
    (a scenario can pass its alert-handling wrapper).
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

    x = y = 0

    def follow(points: Path) -> None:
        nonlocal x, y
        for px, py, pause in points:
            actions.move_by_offset(px - x, py - y)
            x, y = px, py
            actions.pause(pause)

    actions.move_to_element(handle).click_and_hold()
    first = next((i for i, point in enumerate(path) if point[0] > 0), None)
    head = path[: first + 1] if first is not None else path
    follow(head)
    run()
    responded = True
    if first is not None:
        deadline = time.monotonic() + MOVED_WAIT
        while True:
            responded = moved(snapshot())
            if responded or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
    if not responded:
        actions.release()
        run()
        return DragResult(False, snapshot())
    follow(path[len(head) :])
    run()
    final = snapshot()
    actions.release()
    run()
    return DragResult(True, final)


def release_everything(driver: webdriver.Chrome) -> None:
    """After a failed drag, let go of the mouse so the next attempt starts clean."""
    try:
        ActionChains(driver).reset_actions()
        driver.execute_cdp_cmd(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": 0, "y": 0, "button": "left", "clickCount": 1},
        )
    except Exception:  # noqa: BLE001, S110 - best effort only
        pass
