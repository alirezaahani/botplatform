"""Open the page, tick the checkbox and judge the `create` answers."""

import time
from typing import Any

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By

from botplatform.bots.arcaptcha.responses import drain
from botplatform.bots.arcaptcha.session import Session
from botplatform.bots.utils.browser import POLL_SECONDS, StepTimeout, do, screenshot, wait_for
from botplatform.bots.utils.page_scripts import record_browser_signals
from botplatform.contract import BotResult, Status

CHECKBOX = "#input-checkbox"


def open_and_tick(session: Session) -> BotResult | None:
    """Tick the checkbox. Return the failure this causes, or None if the widget accepted us."""
    driver, ctx, timeouts = session.driver, session.ctx, session.timeouts
    driver.set_page_load_timeout(timeouts.load_page)
    try:
        do(session, lambda: driver.get(session.url))
    except TimeoutException:
        raise StepTimeout("load_page") from None
    ctx.event("page_loaded", {"iframes": len(driver.find_elements(By.TAG_NAME, "iframe"))})
    record_browser_signals(session)
    wait_for(
        session,
        lambda: driver.find_elements(By.CSS_SELECTOR, CHECKBOX),
        timeouts.find_checkbox,
        "find_checkbox",
    )
    screenshot(session, "before-click")
    do(session, lambda: driver.find_element(By.CSS_SELECTOR, CHECKBOX).click(), retry=False)
    ctx.event("checkbox_clicked")

    # A request that failed will never get a response, so there is nothing more to wait for.
    wait_for(
        session,
        lambda: drain(session) or "create" in session.watcher.failed,
        timeouts.create_response,
        "create_response",
    )
    # A later `create` can follow, so keep listening briefly.
    deadline = time.monotonic() + timeouts.more_create_responses
    while time.monotonic() < deadline:
        do(session, lambda: drain(session))
        time.sleep(POLL_SECONDS)
    watcher = session.watcher
    ctx.event(
        "create_requests",
        {
            "post_requests_started": watcher.started.count("create"),
            "failed": watcher.failed.count("create"),
            "responses": len(session.creates),
            "not_counted": [r for r in watcher.ignored if r["name"] == "create"],
        },
    )
    return classify(session)


def types(creates: list[dict[str, Any]]) -> list[str]:
    """The types of the `create` answers we could decode. Only those decide the outcome."""
    return [c["captcha_type"] for c in creates if c["captcha_type"] is not None]


def classify_create(creates: list[dict[str, Any]], create_failed: bool) -> BotResult | None:
    """The failure the `create` answers show, or None if the widget accepted us."""
    if not creates and create_failed:
        return BotResult(
            Status.ERROR, "create_request_failed", "The create request failed before a response"
        )
    seen = types(creates)
    if "block" in seen:
        return BotResult(Status.BLOCKED, "captcha_blocked")
    if not any(create["challenge_id"] for create in creates):
        return BotResult(Status.FAILED, "missing_challenge_id")
    latest = seen[-1] if seen else None
    if latest in {"puzzle", "question", "2fa"}:
        return BotResult(Status.BLOCKED, "challenge_unsolved")
    if latest not in {"accept", "cookie"}:
        # Never guess: a type we have not seen cannot be treated as an accepted checkbox.
        return BotResult(Status.ERROR, "unknown_captcha_type", f"captcha_type={latest!r}")
    return None


def classify(session: Session) -> BotResult | None:
    return classify_create(session.creates, "create" in session.watcher.failed)
