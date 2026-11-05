"""An optional helper for bots that use Selenium. The platform core never imports it.

Starting Chrome, and the calls every step needs: `do` (alert handling), `wait_for` and `screenshot`.
"""

import os
import time
from abc import abstractmethod
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import NoAlertPresentException, UnexpectedAlertPresentException
from selenium.webdriver.chrome.service import Service

from botplatform.bots.utils.profiles import BASELINE, Profile
from botplatform.contract import Bot, BotResult, RunContext, Status

POLL_SECONDS = 0.25


class StepTimeout(Exception):
    """A step ran out of time. `step` becomes the run's reason."""

    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step


def describe(error: Exception, limit: int = 200) -> str:
    """`<TypeName>: <first line of the message, cut to limit>`; just the type name if no message."""
    lines = str(error).removeprefix("Message: ").splitlines()  # Selenium adds that prefix
    first = lines[0][:limit] if lines else ""
    name = type(error).__name__
    return f"{name}: {first}" if first else name


@contextmanager
def chrome(*, headless: bool, profile: Profile = BASELINE) -> Iterator[webdriver.Chrome]:
    """Start the pinned Chrome for Testing, and always quit it.

    The worker image sets `CHROME_BINARY` and `CHROMEDRIVER_BINARY`. Passing the driver path
    explicitly means Selenium Manager never looks for, or downloads, a browser or driver.
    The `profile` adds its own arguments, dropped switches and start-up script on top.
    """
    options = webdriver.ChromeOptions()
    options.binary_location = os.environ["CHROME_BINARY"]
    # Lets `ResponseWatcher` read network events through the DevTools protocol.
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    if headless:
        options.add_argument("--headless=new")
    else:
        # Fill the worker's 1280x800 virtual display, which has no window manager.
        options.add_argument("--window-size=1280,800")
        options.add_argument("--window-position=0,0")
    # Docker's default seccomp profile blocks Chrome's sandbox. See DECISIONS.md 1a.
    options.add_argument("--no-sandbox")
    for argument in profile.args:
        options.add_argument(argument)
    if profile.excluded_switches:
        options.add_experimental_option("excludeSwitches", list(profile.excluded_switches))
    driver = webdriver.Chrome(
        options=options, service=Service(executable_path=os.environ["CHROMEDRIVER_BINARY"])
    )
    try:
        if profile.init_script:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument", {"source": profile.init_script}
            )
        yield driver
    finally:
        driver.quit()


@dataclass
class BrowserSession:
    """The run's context and its browser. Bots that need more state subclass it."""

    ctx: RunContext
    driver: webdriver.Chrome


def do(session: BrowserSession, action: Callable[[], Any], *, retry: bool = True) -> Any:
    """Run any driver call, and deal with a JS `alert()` that interrupts it.

    By default Chrome dismisses the alert and the call raises `UnexpectedAlertPresentException`.
    This records the alert's text as an event, dismisses it if it is somehow still open, and
    then repeats the call. Pass `retry=False` for calls that must not run twice, such as a click:
    they return None after an alert.
    """
    for _ in range(5):
        try:
            return action()
        except UnexpectedAlertPresentException as alert:
            text = str(alert.alert_text or alert.msg or "")[:300]
            session.ctx.event("alert", {"text": text})
            try:
                session.driver.switch_to.alert.dismiss()
            except NoAlertPresentException:
                pass  # Chrome already dismissed it
            if not retry:
                return None
    return action()


def raise_if_alert_open(driver: webdriver.Chrome) -> None:
    """Raise `UnexpectedAlertPresentException` if a JS `alert()` is open, for `do` to handle.

    An open alert freezes the page, and some reads never notice it, such as Chrome's network log.
    Call this before such a read: any ordinary driver command raises while an alert is open.
    """
    driver.execute_script("return 0")


def wait_for(session: BrowserSession, check: Callable[[], Any], seconds: float, step: str) -> Any:
    deadline = time.monotonic() + seconds
    while True:
        result = do(session, check)
        if result:
            return result
        if time.monotonic() >= deadline:
            raise StepTimeout(step)
        time.sleep(POLL_SECONDS)


def screenshot(session: BrowserSession, name: str) -> None:
    def capture() -> None:
        session.ctx.artifact(f"{name}.png", "image/png", session.driver.get_screenshot_as_png())

    try:
        do(session, capture)
    except Exception as error:  # noqa: BLE001 - a missing screenshot must not change the result
        session.ctx.event("screenshot_failed", {"name": name, "error": describe(error)})


BROWSER_MODES = ("headless", "headful")


class SeleniumBot(Bot):
    """A bot that drives Chrome. Implement `steps`; this picks the profile for the mode, starts
    Chrome, records the profile, and turns a `StepTimeout` into a `timeout` result.

    Any other exception gets a screenshot named `error` and propagates to the worker, which turns
    it into an `unhandled_exception` result. `profile_by_mode` overrides `profile` for the modes
    it lists.
    """

    def __init__(
        self,
        id: str,
        name: str,
        description: str = "",
        modes: Sequence[str] = BROWSER_MODES,
        *,
        profile: Profile = BASELINE,
        profile_by_mode: dict[str, Profile] | None = None,
    ) -> None:
        super().__init__(id, name, description, modes)
        # A mistyped mode would silently run headful (`headless=ctx.mode == "headless"`).
        if unknown := [mode for mode in self.modes if mode not in BROWSER_MODES]:
            raise ValueError(f"Bot '{id}' has modes {unknown}, which Chrome cannot run")
        # A mistyped key would silently fall back to `profile`.
        if unlisted := [mode for mode in profile_by_mode or {} if mode not in self.modes]:
            raise ValueError(f"Bot '{id}' has profiles for {unlisted}, which are not its modes")
        self.profile = profile
        self.profile_by_mode = profile_by_mode or {}

    def profile_for(self, mode: str) -> Profile:
        """The browser profile for `mode`: the one listed for it, else `profile`."""
        return self.profile_by_mode.get(mode, self.profile)

    def run(self, ctx: RunContext) -> BotResult:
        profile = self.profile_for(ctx.mode)
        with chrome(headless=ctx.mode == "headless", profile=profile) as driver:
            browser = BrowserSession(ctx, driver)
            try:
                ctx.event("browser_profile", profile.settings())
                return self.steps(browser)
            except StepTimeout as timeout:
                screenshot(browser, f"timeout-{timeout.step}")
                return BotResult(
                    Status.TIMEOUT, timeout.step, f"Timed out in step '{timeout.step}'"
                )
            except Exception:
                screenshot(browser, "error")
                raise

    @abstractmethod
    def steps(self, browser: BrowserSession) -> BotResult:
        """Do the work with the started browser and return the outcome."""
