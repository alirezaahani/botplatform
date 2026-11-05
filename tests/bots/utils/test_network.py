"""Watching the network: which requests are captured, and how a captured exchange is recorded."""

import socket
import time
from collections.abc import Callable

import pytest
from selenium import webdriver

from botplatform.bots.utils.network import (
    CapturedResponse,
    ResponseWatcher,
    exchange_record,
    path_endswith,
)
from tests.bots.utils.conftest import LocalPage

WATCH_SECONDS = 5
# Once the request has been seen, how long to keep reading for anything that follows it.
SETTLE_SECONDS = 1


def response(body: bytes | None, error: str | None = None, **kwargs) -> CapturedResponse:
    return CapturedResponse("create", "u", 201, body, error, **kwargs)


def test_a_readable_exchange_is_decoded_on_both_sides():
    record = exchange_record(response(b'{"captcha_type": "accept"}', request_body=b'{"a": 1}'))

    assert (record["request"], record["response"]) == ({"a": 1}, {"captcha_type": "accept"})
    assert not [key for key in record if key.endswith("_note")]


def test_a_bot_can_pass_its_own_decoder():
    record = exchange_record(response(b"abc", request_body=b"x"), lambda data: len(data))

    assert (record["request"], record["response"]) == (1, 3)


@pytest.mark.parametrize(
    ("captured", "side", "note_starts_with"),
    [
        pytest.param(response(None, "WebDriverException: gone"), "response", "no body: WebDriver"),
        pytest.param(response(b"\x01\x02\x03"), "response", "decode failed"),
        pytest.param(
            response(b"{}", request_body=b"\x01\x02", request_body_error=None),
            "request",
            "decode failed",
        ),
    ],
    ids=["no-response-body", "undecodable-response", "undecodable-request"],
)
def test_a_body_that_cannot_be_read_is_noted_and_does_not_raise(captured, side, note_starts_with):
    record = exchange_record(captured)

    assert record[side] is None
    assert record[f"{side}_note"].startswith(note_starts_with)
    assert record["http_status"] == 201


def test_an_undecodable_body_keeps_the_start_of_its_text():
    record = exchange_record(response(b"<html>oops</html>" + b"x" * 900))

    assert record["response"] is None
    assert record["response_text"] == ("<html>oops</html>" + "x" * 900)[:500]


def test_a_path_matches_with_or_without_a_query_string():
    matches = path_endswith("/api/create")

    assert matches("https://site/api/create")
    assert matches("https://site/api/create?v=2")
    assert not matches("https://site/api/created")


# -- What the watcher captures, in real Chrome --------------------------------------------------


def watch(
    driver: webdriver.Chrome, watcher: ResponseWatcher, until: Callable[[], bool]
) -> list[CapturedResponse]:
    """Poll the watcher until `until()` holds, then a little longer. Fails if it never holds."""
    found: list[CapturedResponse] = []
    deadline = time.monotonic() + WATCH_SECONDS
    while not until():
        assert time.monotonic() < deadline, "the watcher never saw the request"
        found += watcher.poll()
        time.sleep(0.1)
    settle = time.monotonic() + SETTLE_SECONDS
    while time.monotonic() < settle:
        found += watcher.poll()
        time.sleep(0.1)
    return found


def echo_watcher(driver: webdriver.Chrome, **options) -> ResponseWatcher:
    return ResponseWatcher(driver, {"echo": path_endswith("/api/echo")}, **options)


def test_a_post_is_captured_with_both_bodies(driver, local_page: LocalPage):
    watcher = echo_watcher(driver)
    driver.get(local_page.url)
    driver.execute_script("fetch('/api/echo', {method: 'POST', body: 'hello'})")

    found = watch(driver, watcher, lambda: bool(watcher.started))

    assert [(r.name, r.status, r.request_body) for r in found] == [("echo", 201, b"hello")]
    assert found[0].body == b'{"name":"echo","got":"hello"}'


def test_a_get_is_only_noted_unless_gets_are_watched(driver, local_page: LocalPage):
    watcher = echo_watcher(driver)
    driver.get(local_page.url)
    driver.execute_script("fetch('/api/echo')")

    assert watch(driver, watcher, lambda: bool(watcher.ignored)) == []
    assert watcher.ignored[0]["method"] == "GET"


def test_a_get_is_captured_when_gets_are_watched(driver, local_page: LocalPage):
    watcher = echo_watcher(driver, methods=("GET",))
    driver.get(local_page.url)
    driver.execute_script("fetch('/api/echo')")

    found = watch(driver, watcher, lambda: bool(watcher.started))

    assert [(r.name, r.status) for r in found] == [("echo", 201)]


def test_a_cross_origin_preflight_is_not_counted(driver, local_page: LocalPage):
    other = LocalPage()
    other.server.start()
    try:
        watcher = echo_watcher(driver)
        driver.get(local_page.url)
        # A JSON content type makes the cross-origin POST send an OPTIONS preflight first.
        driver.execute_script(
            "fetch(arguments[0], {method: 'POST', body: '{}',"
            " headers: {'Content-Type': 'application/json'}})",
            other.origin + "/api/echo",
        )
        found = watch(driver, watcher, lambda: bool(watcher.started))
    finally:
        other.server.stop()

    assert [(r.name, r.status) for r in found] == [("echo", 201)]
    assert [entry["method"] for entry in watcher.ignored] == ["OPTIONS"]


def test_a_request_that_fails_before_a_response_is_listed_as_failed(driver, local_page):
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]  # free, and nothing listens once it is closed
    watcher = echo_watcher(driver)
    driver.get(local_page.url)
    driver.execute_script(
        "fetch(arguments[0], {method: 'POST', body: 'x'}).catch(() => {})",
        f"http://127.0.0.1:{port}/api/echo",
    )

    assert watch(driver, watcher, lambda: bool(watcher.failed)) == []
    assert watcher.failed == ["echo"]
