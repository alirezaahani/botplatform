"""The helpers every Selenium bot uses: error text, alerts, waiting, and `SeleniumBot`."""

import time
from collections.abc import Callable

import pytest
from selenium import webdriver
from selenium.common.exceptions import WebDriverException

from botplatform.bots.utils.browser import (
    BrowserMode,
    BrowserSession,
    SeleniumBot,
    StepTimeout,
    describe,
    do,
    raise_if_alert_open,
    wait_for,
)
from botplatform.bots.utils.profiles import BASELINE, STEALTH_FLAGS
from botplatform.contract import BotResult, Status
from tests.bots.utils.conftest import LocalPage
from tests.conftest import RecordingContext

# Long enough for a `setTimeout(..., 0)` alert to open.
ALERT_DELAY = 0.3


def test_a_selenium_error_is_described_by_its_type_and_first_line():
    assert describe(WebDriverException("unknown error\nstack trace")) == (
        "WebDriverException: unknown error"
    )


def test_an_error_with_an_empty_message_is_described_without_raising():
    assert describe(WebDriverException("")).startswith("WebDriverException")
    assert describe(RuntimeError()) == "RuntimeError"


def test_a_step_timeout_names_the_step():
    assert "login_response" in describe(StepTimeout("login_response"))


# -- Alerts and waiting -------------------------------------------------------------------------


def open_alert(driver: webdriver.Chrome, page: LocalPage) -> None:
    driver.get(page.url)
    driver.execute_script("setTimeout(() => alert('hello'), 0)")
    time.sleep(ALERT_DELAY)


def test_do_records_an_alert_and_repeats_the_call(driver, local_page):
    ctx = RecordingContext()
    open_alert(driver, local_page)

    assert do(BrowserSession(ctx, driver), lambda: driver.execute_script("return 1 + 1")) == 2
    assert ctx.one("alert") == {"text": "hello"}


def test_do_without_retry_does_not_repeat_the_call_after_an_alert(driver, local_page):
    ctx = RecordingContext()
    open_alert(driver, local_page)
    calls = []

    def click() -> int:
        calls.append(1)
        return driver.execute_script("return 1")

    assert do(BrowserSession(ctx, driver), click, retry=False) is None
    assert len(calls) == 1
    assert ctx.one("alert") == {"text": "hello"}


def test_an_open_alert_is_noticed_before_a_read_that_cannot_see_it(driver, local_page):
    ctx = RecordingContext()
    open_alert(driver, local_page)

    do(BrowserSession(ctx, driver), lambda: raise_if_alert_open(driver))

    assert ctx.one("alert") == {"text": "hello"}
    raise_if_alert_open(driver)  # dismissed: nothing is open any more


def test_wait_for_returns_the_first_truthy_result(driver):
    answers = iter([None, [], "ready"])

    assert wait_for(BrowserSession(RecordingContext(), driver), lambda: next(answers), 5, "s") == (
        "ready"
    )


def test_wait_for_raises_a_step_timeout_naming_the_step(driver):
    with pytest.raises(StepTimeout) as raised:
        wait_for(BrowserSession(RecordingContext(), driver), lambda: None, 0.3, "find_thing")
    assert raised.value.step == "find_thing"


# -- SeleniumBot --------------------------------------------------------------------------------


class ProbeBot(SeleniumBot):
    """Runs the given function as its steps."""

    def __init__(self, work: Callable[[BrowserSession], BotResult], **options) -> None:
        super().__init__("probe", "Probe bot", **options)
        self.work = work

    def steps(self, browser: BrowserSession) -> BotResult:
        return self.work(browser)


def succeed(browser: BrowserSession) -> BotResult:
    return BotResult(Status.SUCCESS)


def test_the_profile_is_picked_by_mode():
    bot = ProbeBot(succeed, profile=BASELINE, profile_by_mode={BrowserMode.HEADLESS: STEALTH_FLAGS})

    assert bot.profile_for(BrowserMode.HEADLESS) is STEALTH_FLAGS
    assert bot.profile_for(BrowserMode.HEADFUL) is BASELINE


def test_a_run_records_its_profile_and_returns_what_the_steps_return(local_page):
    def visit(browser: BrowserSession) -> BotResult:
        browser.driver.get(local_page.url)
        return BotResult(Status.FAILED, "probe_reason")

    ctx = RecordingContext()
    result = ProbeBot(visit, profile=STEALTH_FLAGS).run(ctx, BrowserMode.HEADLESS)

    assert result == BotResult(Status.FAILED, "probe_reason")
    assert ctx.one("browser_profile") == STEALTH_FLAGS.settings()


def test_a_step_timeout_ends_the_run_as_timeout_with_a_screenshot(local_page):
    def stall(browser: BrowserSession) -> BotResult:
        browser.driver.get(local_page.url)
        raise StepTimeout("find_thing")

    ctx = RecordingContext()
    result = ProbeBot(stall).run(ctx, BrowserMode.HEADLESS)

    assert (result.status, result.reason) == (Status.TIMEOUT, "find_thing")
    assert [name for name, _, _ in ctx.artifacts] == ["timeout-find_thing.png"]


def test_any_other_error_propagates_after_a_screenshot(local_page):
    def crash(browser: BrowserSession) -> BotResult:
        browser.driver.get(local_page.url)
        raise RuntimeError("boom")

    ctx = RecordingContext()
    with pytest.raises(RuntimeError, match="boom"):
        ProbeBot(crash).run(ctx, BrowserMode.HEADLESS)
    assert [name for name, _, _ in ctx.artifacts] == ["error.png"]
