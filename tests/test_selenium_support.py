"""`describe`, the one-line text for a recorded exception. No Chrome."""

from selenium.common.exceptions import WebDriverException

from botplatform.bots.arcaptcha.timeouts import StepTimeout
from botplatform.bots.selenium_support import describe


def test_a_selenium_error_is_described_by_its_type_and_first_line():
    assert describe(WebDriverException("unknown error\nstack trace")) == (
        "WebDriverException: unknown error"
    )


def test_an_error_with_an_empty_message_is_described_without_raising():
    assert describe(WebDriverException("")).startswith("WebDriverException")
    assert describe(RuntimeError()) == "RuntimeError"


def test_a_step_timeout_names_the_step():
    assert "login_response" in describe(StepTimeout("login_response"))
