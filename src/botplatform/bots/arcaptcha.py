"""The ARCaptcha demo bot: tick the checkbox, read `challenge_id`, log in, verify the result."""

import json
import os
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By

from botplatform.bots.arcaptcha_codec import decode_body
from botplatform.bots.selenium_support import (
    CapturedResponse,
    ResponseWatcher,
    call_handling_alerts,
    chrome,
)
from botplatform.contract import Bot, BotResult, RunContext, Status

DEMO_URL = "https://demo.arcaptcha.co/"
CHECKBOX = "#input-checkbox"
TOAST = ".Vue-Toastification__toast"
# vue-toastification adds `Vue-Toastification__toast--<type>`; the demo calls `success` or `error`.
TOAST_SUCCESS = "Vue-Toastification__toast--success"
TOAST_ERROR = "Vue-Toastification__toast--error"
LOGIN_BUTTON = "//button[normalize-space()='Login']"
CHALLENGE_TYPES = {"puzzle", "question", "2fa"}
ACCEPTED_TYPES = {"accept", "cookie"}

POLL_SECONDS = 0.25


@dataclass(frozen=True)
class StepTimeouts:
    """Seconds allowed for each step. The defaults stay well below the run time limit."""

    load_page: float = 30
    find_checkbox: float = 15
    create_response: float = 20
    more_create_responses: float = 2
    login_response: float = 15
    toast: float = 5


DEFAULT_TIMEOUTS = StepTimeouts()


# Reads the challenge ID three ways, separately, so each answer stays distinct. The widget list is
# `window.arcaptcha.widgets`, keyed by widget ID (from widget.arcaptcha.ir/1/api.js).
WIDGET_CHALLENGE_ID_JS = """
const attempt = (read) => {
  try { return {value: read() || null}; } catch (error) { return {error: String(error)}; }
};
const arc = window.arcaptcha;
const widgets = arc && arc.widgets ? arc.widgets : null;
const ids = widgets ? Object.keys(widgets) : [];
const widget = ids.length ? widgets[ids[0]] : null;
const hidden = document.querySelector('#arcaptcha-token');
return {
  arcaptcha_present: !!arc,
  widget_ids: ids,
  widget_has_get_challenge_id: !!widget && typeof widget.getChallengeID === 'function',
  widget_value: widget && typeof widget.getChallengeID === 'function'
    ? attempt(() => widget.getChallengeID()) : null,
  get_arc_token: arc && typeof arc.getArcToken === 'function' && ids.length
    ? attempt(() => arc.getArcToken(ids[0])) : null,
  hidden_field: hidden ? {value: hidden.value || null} : null
};
"""
# Screenshots must never show the password, so the field is blanked first.
BLANK_PASSWORD_JS = "document.querySelectorAll('input[type=password]').forEach(e => e.value = '')"


class StepTimeout(Exception):
    """A step ran out of time. `step` becomes the run's reason."""

    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step


class ArcaptchaBot(Bot):
    id = "arcaptcha"
    name = "ARCaptcha demo (Selenium)"
    description = (
        "Ticks the checkbox on demo.arcaptcha.co, records challenge_id, logs in and checks that "
        "the login really succeeded."
    )
    modes: ClassVar[list[str]] = ["headless"]

    def __init__(self, url: str = DEMO_URL, timeouts: StepTimeouts = DEFAULT_TIMEOUTS) -> None:
        self.url = url
        self.timeouts = timeouts

    def run(self, ctx: RunContext) -> BotResult:
        username = os.environ.get("ARCAPTCHA_USERNAME")
        password = os.environ.get("ARCAPTCHA_PASSWORD")
        if not username or not password:
            return BotResult(
                Status.ERROR,
                "missing_credentials",
                "Set ARCAPTCHA_USERNAME and ARCAPTCHA_PASSWORD in .env",
            )
        try:
            with chrome(headless=ctx.mode == "headless") as driver:
                return Scenario(ctx, driver, username, password, self.url, self.timeouts).run()
        except Exception:  # noqa: BLE001 - every failure becomes an error result, minus the password
            # The password must never reach the run's error field, whatever the exception says.
            details = traceback.format_exc().replace(password, "[password]")
            return BotResult(Status.ERROR, "unhandled_exception", details)


class Scenario:
    def __init__(
        self,
        ctx: RunContext,
        driver: webdriver.Chrome,
        username: str,
        password: str,
        url: str = DEMO_URL,
        timeouts: StepTimeouts = DEFAULT_TIMEOUTS,
    ) -> None:
        self.ctx = ctx
        self.driver = driver
        self.username = username
        self.password = password
        self.url = url
        self.timeouts = timeouts
        self.watcher = ResponseWatcher(
            driver,
            {
                "create": lambda url: url.split("?")[0].endswith("/api/create"),
                "login": lambda url: url.split("?")[0].endswith("/api/login"),
            },
        )
        self.creates: list[dict[str, Any]] = []
        self.logins: list[CapturedResponse] = []

    def run(self) -> BotResult:
        try:
            return self._run()
        except StepTimeout as timeout:
            self._screenshot(f"timeout-{timeout.step}")
            return BotResult(Status.TIMEOUT, timeout.step, f"Timed out in step '{timeout.step}'")
        except Exception:
            self._screenshot("error")
            raise

    def _run(self) -> BotResult:
        earlier = self._open_and_tick()
        self._screenshot("after-click")
        # Decision 3b: the login is always attempted, but it can never upgrade an earlier failure.
        try:
            verdict = self._log_in()
        except StepTimeout as timeout:
            if earlier:
                self.ctx.event("login_timeout", {"step": timeout.step})
                self._screenshot("login-timeout")
                return earlier
            raise
        except Exception as error:
            if not earlier:
                raise
            self.ctx.event("login_error", {"type": type(error).__name__})
            self._screenshot("login-error")
            return earlier
        self._screenshot("after-login")
        # Both steps found nothing wrong, so this is the only place a run can succeed.
        return earlier or verdict or BotResult(Status.SUCCESS)

    # -- Steps -------------------------------------------------------------------------------

    def _open_and_tick(self) -> BotResult | None:
        """Tick the checkbox. Return the failure this causes, or None if the widget accepted us."""
        driver = self.driver
        driver.set_page_load_timeout(self.timeouts.load_page)
        try:
            self._do(lambda: driver.get(self.url))
        except TimeoutException:
            raise StepTimeout("load_page") from None
        self.ctx.event("page_loaded", {"iframes": len(driver.find_elements(By.TAG_NAME, "iframe"))})
        self._wait_for(
            lambda: driver.find_elements(By.CSS_SELECTOR, CHECKBOX),
            self.timeouts.find_checkbox,
            "find_checkbox",
        )
        self._screenshot("before-click")
        self.ctx.event("widget_challenge_id_before_click", self._widget_challenge_id())
        self._do(lambda: driver.find_element(By.CSS_SELECTOR, CHECKBOX).click(), retry=False)
        self.ctx.event("checkbox_clicked")

        self._wait_for(self._drain, self.timeouts.create_response, "create_response")
        # A later `create` can follow, so keep listening briefly.
        deadline = time.monotonic() + self.timeouts.more_create_responses
        while time.monotonic() < deadline:
            self._drain()
            time.sleep(POLL_SECONDS)
        self.ctx.event("widget_challenge_id_after_click", self._widget_challenge_id())
        self.ctx.event(
            "create_requests",
            {
                "post_requests_started": self.watcher.started.count("create"),
                "failed": self.watcher.failed.count("create"),
                "responses": len(self.creates),
                "not_counted": [r for r in self.watcher.ignored if r["name"] == "create"],
            },
        )
        return self._classify_create()

    def _log_in(self) -> BotResult | None:
        """Submit the form. Return a failure if the result is not confirmed by both signals."""
        driver = self.driver
        self._do(lambda: driver.find_element(By.ID, "email").send_keys(self.username), retry=False)
        self._do(
            lambda: driver.find_element(By.ID, "password").send_keys(self.password), retry=False
        )
        self.ctx.event("login_submitted")
        self._do(lambda: driver.find_element(By.XPATH, LOGIN_BUTTON).click(), retry=False)

        self._wait_for(
            lambda: self._drain() and self.logins,
            self.timeouts.login_response,
            "login_response",
        )
        login = self.logins[-1]
        body = self._json_body(login)
        self.ctx.event(
            "login_response", {"http_status": login.status, "body": self._body_text(login)}
        )

        # The response has arrived, so a missing toast is a disagreement, not a timeout.
        try:
            toast = self._wait_for(self._toast, self.timeouts.toast, "toast")
        except StepTimeout:
            toast = {"kind": "none", "text": ""}
        self.ctx.event("toast", toast)
        message = body.get("msg") if isinstance(body, dict) else None
        confirmed = (
            login.status == 200
            and toast["kind"] == "success"
            and isinstance(message, str)
            and message in toast["text"]
        )
        if confirmed:
            return None
        return BotResult(
            Status.FAILED,
            "verification_failed",
            f"Login returned HTTP {login.status} and the toast was '{toast['kind']}'",
        )

    # -- Helpers -----------------------------------------------------------------------------

    def _do(self, action: Callable[[], Any], *, retry: bool = True) -> Any:
        """Run any driver call. A JS `alert()` is recorded and dismissed instead of crashing it."""

        def on_alert(text: str) -> None:
            self.ctx.event("alert", {"text": text})

        return call_handling_alerts(self.driver, action, on_alert, retry=retry)

    def _wait_for(self, check: Callable[[], Any], seconds: float, step: str) -> Any:
        deadline = time.monotonic() + seconds
        while True:
            result = self._do(check)
            if result:
                return result
            if time.monotonic() >= deadline:
                raise StepTimeout(step)
            time.sleep(POLL_SECONDS)

    def _drain(self) -> bool:
        """Read new network responses. Each `create` is recorded the moment it is seen."""
        seen_create = False
        for response in self.watcher.poll():
            if response.name == "login":
                self.logins.append(response)
            else:
                self._handle_create(response)
                seen_create = True
        return seen_create or bool(self.logins)

    def _handle_create(self, response: CapturedResponse) -> None:
        info: dict[str, Any] = {"http_status": response.status, "captcha_type": None}
        challenge_id = None
        if response.body is None:
            info["body_error"] = response.body_error
        else:
            try:
                decoded = decode_body(response.body)
                info["captcha_type"] = decoded.get("captcha_type")
                challenge_id = (decoded.get("content") or {}).get("challenge_id")
            except (ValueError, AttributeError, TypeError) as error:
                info["decode_error"] = type(error).__name__
        if not isinstance(challenge_id, str) or not challenge_id:
            challenge_id = None
        self.creates.append({"captcha_type": info["captcha_type"], "challenge_id": challenge_id})
        info["has_challenge_id"] = challenge_id is not None
        if challenge_id:
            self.ctx.record_challenge_id(challenge_id)
        self.ctx.event("create_response", info)

    def _classify_create(self) -> BotResult | None:
        # A response we could not decode has no type, so only decoded ones decide the outcome.
        types = [c["captcha_type"] for c in self.creates if c["captcha_type"] is not None]
        if "block" in types:
            return BotResult(Status.BLOCKED, "captcha_blocked")
        if not any(create["challenge_id"] for create in self.creates):
            return BotResult(Status.FAILED, "missing_challenge_id")
        latest = types[-1] if types else None
        if latest in CHALLENGE_TYPES:
            return BotResult(Status.BLOCKED, "challenge_unsolved")
        if latest not in ACCEPTED_TYPES:
            # Never guess: a type we have not seen cannot be treated as an accepted checkbox.
            return BotResult(Status.ERROR, "unknown_captcha_type", f"captcha_type={latest!r}")
        return None

    def _widget_challenge_id(self) -> dict[str, Any]:
        return self._do(lambda: self.driver.execute_script(WIDGET_CHALLENGE_ID_JS)) or {}

    def _toast(self) -> dict[str, str] | None:
        try:
            toast = self.driver.find_element(By.CSS_SELECTOR, TOAST)
        except NoSuchElementException:
            return None
        classes = toast.get_attribute("class") or ""
        kind = (
            "success"
            if TOAST_SUCCESS in classes
            else "error"
            if TOAST_ERROR in classes
            else "other"
        )
        text = toast.text.strip()
        # The toast animates in, so its text can be empty for a moment. Wait for the message.
        return {"kind": kind, "text": text[:300]} if text else None

    @staticmethod
    def _json_body(response: CapturedResponse) -> Any:
        try:
            return json.loads(response.body.decode("utf-8")) if response.body else None
        except ValueError:
            return None

    @staticmethod
    def _body_text(response: CapturedResponse) -> Any:
        if response.body is None:
            return {"unreadable": response.body_error}
        parsed = Scenario._json_body(response)
        if parsed is not None:
            return parsed
        return response.body.decode("utf-8", errors="replace")[:500]

    def _screenshot(self, name: str) -> None:
        def capture() -> None:
            self.driver.execute_script(BLANK_PASSWORD_JS)
            self.ctx.artifact(f"{name}.png", "image/png", self.driver.get_screenshot_as_png())

        try:
            self._do(capture)
        except Exception as error:  # noqa: BLE001 - a missing screenshot must not change the result
            self.ctx.event("screenshot_failed", {"name": name, "type": type(error).__name__})
