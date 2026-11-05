"""Page steps: load, tick the checkbox, wait for the `create`, log in."""

import time
from typing import Any

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By

from botplatform.bots.arcaptcha.js import BROWSER_SIGNALS_JS, WIDGET_CHALLENGE_ID_JS
from botplatform.bots.arcaptcha.session import Session, do, screenshot, wait_for
from botplatform.bots.arcaptcha.timeouts import POLL_SECONDS, StepTimeout
from botplatform.bots.arcaptcha.traffic import classify, drain
from botplatform.bots.selenium_support import describe
from botplatform.contract import BotResult, Status

CHECKBOX = "#input-checkbox"
TOAST = ".Vue-Toastification__toast"
# vue-toastification adds `Vue-Toastification__toast--<type>`; the demo calls `success` or `error`.
TOAST_SUCCESS = "Vue-Toastification__toast--success"
TOAST_ERROR = "Vue-Toastification__toast--error"
LOGIN_BUTTON = "//button[normalize-space()='Login']"


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
    ctx.event("widget_challenge_id_before_click", widget_challenge_id(session))
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
    ctx.event("widget_challenge_id_after_click", widget_challenge_id(session))
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


def log_in(session: Session) -> BotResult | None:
    """Submit the form. Return a failure if the result is not confirmed by both signals."""
    driver, ctx = session.driver, session.ctx
    do(
        session,
        lambda: driver.find_element(By.ID, "email").send_keys(session.username),
        retry=False,
    )
    do(
        session,
        lambda: driver.find_element(By.ID, "password").send_keys(session.password),
        retry=False,
    )
    ctx.event("login_submitted")
    do(session, lambda: driver.find_element(By.XPATH, LOGIN_BUTTON).click(), retry=False)

    wait_for(
        session,
        lambda: (drain(session) and session.logins) or "login" in session.watcher.failed,
        session.timeouts.login_response,
        "login_response",
    )
    if not session.logins:
        ctx.event("login_request_failed")
        return BotResult(
            Status.ERROR, "login_request_failed", "The login request failed before a response"
        )
    login = session.logins[-1]

    # The response has arrived, so a missing toast is a disagreement, not a timeout.
    try:
        toast = wait_for(session, lambda: read_toast(session), session.timeouts.toast, "toast")
    except StepTimeout:
        toast = {"kind": "none", "text": ""}
    ctx.event("toast", toast)
    return verify_login(login["http_status"], login["response"], toast)


def verify_login(http_status: int, body: Any, toast: dict[str, str]) -> BotResult | None:
    """None if the HTTP response and the toast both confirm the login, else `verification_failed`.

    Both signals are needed: the status is 200 and the toast is a success toast that shows the
    message from the response body.
    """
    message = body.get("msg") if isinstance(body, dict) else None
    confirmed = (
        http_status == 200
        and toast["kind"] == "success"
        and isinstance(message, str)
        and message in toast["text"]
    )
    if confirmed:
        return None
    return BotResult(
        Status.FAILED,
        "verification_failed",
        f"Login returned HTTP {http_status} and the toast was '{toast['kind']}'",
    )


def read_toast(session: Session) -> dict[str, str] | None:
    try:
        toast = session.driver.find_element(By.CSS_SELECTOR, TOAST)
    except NoSuchElementException:
        return None
    classes = toast.get_attribute("class") or ""
    kind = "success" if TOAST_SUCCESS in classes else "error" if TOAST_ERROR in classes else "other"
    text = toast.text.strip()
    # The toast animates in, so its text can be empty for a moment. Wait for the message.
    return {"kind": kind, "text": text[:300]} if text else None


def widget_challenge_id(session: Session) -> dict[str, Any]:
    return do(session, lambda: session.driver.execute_script(WIDGET_CHALLENGE_ID_JS)) or {}


def record_browser_signals(session: Session) -> None:
    try:
        signals = do(session, lambda: session.driver.execute_async_script(BROWSER_SIGNALS_JS))
    except Exception as error:  # noqa: BLE001 - evidence gathering must not change the result
        signals = {"error": describe(error)}
    session.ctx.event("browser_signals", signals if isinstance(signals, dict) else {})
