"""An optional helper for bots that use Selenium. The platform core never imports it."""

import base64
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from selenium import webdriver
from selenium.common.exceptions import (
    NoAlertPresentException,
    UnexpectedAlertPresentException,
    WebDriverException,
)
from selenium.webdriver.chrome.service import Service


def call_handling_alerts[T](
    driver: webdriver.Chrome,
    action: Callable[[], T],
    on_alert: Callable[[str], None],
    *,
    retry: bool = True,
) -> T | None:
    """Run one driver call, and deal with a JS `alert()` that interrupts it.

    By default Chrome dismisses the alert and the call raises `UnexpectedAlertPresentException`.
    This reports the alert's text to `on_alert`, dismisses it if it is somehow still open, and
    then repeats the call. Pass `retry=False` for calls that must not run twice, such as a click:
    they return None after an alert.
    """
    for _ in range(5):
        try:
            return action()
        except UnexpectedAlertPresentException as alert:
            on_alert(str(alert.alert_text or alert.msg or "")[:300])
            try:
                driver.switch_to.alert.dismiss()
            except NoAlertPresentException:
                pass  # Chrome already dismissed it
            if not retry:
                return None
    return action()


@contextmanager
def chrome(*, headless: bool) -> Iterator[webdriver.Chrome]:
    """Start the pinned Chrome for Testing, and always quit it.

    The worker image sets `CHROME_BINARY` and `CHROMEDRIVER_BINARY`. Passing the driver path
    explicitly means Selenium Manager never looks for, or downloads, a browser or driver.
    """
    options = webdriver.ChromeOptions()
    options.binary_location = os.environ["CHROME_BINARY"]
    # Lets `ResponseWatcher` read network events through the DevTools protocol.
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    if headless:
        options.add_argument("--headless=new")
    # Docker's default seccomp profile blocks Chrome's sandbox. See DECISIONS.md 1a.
    options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(
        options=options, service=Service(executable_path=os.environ["CHROMEDRIVER_BINARY"])
    )
    try:
        yield driver
    finally:
        driver.quit()


@dataclass(frozen=True)
class CapturedResponse:
    """A finished network response. `body` is None if Chrome could not give it to us."""

    name: str
    url: str
    status: int
    body: bytes | None
    body_error: str | None = None


class ResponseWatcher:
    """Collects finished responses for chosen URLs, from Chrome's DevTools network events.

    Call `poll()` regularly. Responses come back in the order they finished. Only POST
    requests count: a cross-origin call also logs a CORS preflight for the same URL, which is
    ignored because its method is `OPTIONS` (Chrome 156 gives it the type `Other`). Request bodies are never read or stored, so a
    password sent in a login request is never captured.
    """

    def __init__(self, driver: webdriver.Chrome, matchers: dict[str, Callable[[str], bool]]):
        self._driver = driver
        self._matchers = matchers
        self._pending: dict[str, tuple[str, str, int]] = {}  # request id -> name, url, status
        self._tracked: dict[str, str] = {}  # request id -> name, for real POST requests
        # Matching requests that were not counted, such as CORS preflights, for the run's record.
        self.ignored: list[dict[str, str | None]] = []
        self.started: list[str] = []  # names of real POST requests, in the order they started
        self.failed: list[str] = []  # names of tracked requests that failed before a response

    def poll(self) -> list[CapturedResponse]:
        found: list[CapturedResponse] = []
        for entry in self._driver.get_log("performance"):
            message = json.loads(entry["message"])["message"]
            params = message.get("params", {})
            request_id = params.get("requestId")
            if message["method"] == "Network.requestWillBeSent":
                self._see_request(request_id, params)
            elif message["method"] == "Network.responseReceived":
                if request_id in self._tracked:
                    response = params["response"]
                    name = self._tracked[request_id]
                    self._pending[request_id] = (name, response["url"], response["status"])
            elif message["method"] == "Network.loadingFinished" and request_id in self._pending:
                name, url, status = self._pending.pop(request_id)
                self._tracked.pop(request_id, None)
                found.append(self._read_body(request_id, name, url, status))
            elif message["method"] == "Network.loadingFailed":
                self._pending.pop(request_id, None)
                if request_id in self._tracked:
                    self.failed.append(self._tracked.pop(request_id))
        return found

    def _see_request(self, request_id: str, params: dict) -> None:
        request = params["request"]
        name = next((n for n, matches in self._matchers.items() if matches(request["url"])), None)
        if name is None:
            return
        if request["method"] == "POST":
            self._tracked[request_id] = name
            self.started.append(name)
        else:
            self.ignored.append(
                {"name": name, "method": request["method"], "type": params.get("type")}
            )

    def _read_body(self, request_id: str, name: str, url: str, status: int) -> CapturedResponse:
        try:
            result = self._driver.execute_cdp_cmd(
                "Network.getResponseBody", {"requestId": request_id}
            )
        except WebDriverException as error:
            reason = f"{type(error).__name__}: {(error.msg or '').splitlines()[0][:200]}"
            return CapturedResponse(name, url, status, None, reason)
        body = result["body"]
        data = base64.b64decode(body) if result.get("base64Encoded") else body.encode("utf-8")
        return CapturedResponse(name, url, status, data)
