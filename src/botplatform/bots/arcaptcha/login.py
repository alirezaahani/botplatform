"""Log in and check that the login really succeeded."""

from typing import Any

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from botplatform.bots.arcaptcha.responses import drain
from botplatform.bots.arcaptcha.session import Session
from botplatform.bots.utils.browser import StepTimeout, do, wait_for
from botplatform.contract import BotResult, Status

TOAST = ".Vue-Toastification__toast"
# vue-toastification adds `Vue-Toastification__toast--<type>`; the demo calls `success` or `error`.
TOAST_SUCCESS = "Vue-Toastification__toast--success"
TOAST_ERROR = "Vue-Toastification__toast--error"
LOGIN_BUTTON = "//button[normalize-space()='Login']"


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
    match body:
        case {"msg": str() as message}:
            pass
        case _:
            message = None
    confirmed = (
        http_status == 200
        and toast["kind"] == "success"
        and message is not None
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
