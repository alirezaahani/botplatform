"""Scripts run in the page: the browser signals, and fetching files with the page's origin."""

import pytest

from botplatform.bots.utils.browser import BrowserSession
from botplatform.bots.utils.page_scripts import (
    FetchedFile,
    fetch_in_page,
    record_browser_signals,
    save_fetched,
)
from tests.conftest import RecordingContext

# What `record_browser_signals` reports. The profile tests read these to judge a profile.
SIGNAL_KEYS = {
    "webdriver", "user_agent", "platform", "languages", "plugins", "mime_types",
    "hardware_concurrency", "device_memory", "chrome", "window", "screen",
    "notification_permission", "permissions_notifications", "webgl", "automation_properties",
}  # fmt: skip


def test_the_browser_signals_are_recorded(driver, local_page):
    ctx = RecordingContext()
    driver.get(local_page.url)

    record_browser_signals(BrowserSession(ctx, driver))

    assert SIGNAL_KEYS <= ctx.one("browser_signals").keys()


def test_files_are_fetched_in_order_with_their_content_types(driver, local_page):
    local_page.files = {"a": (b"\x89PNG fake", "image/png"), "b": (b"\x00\x01", None)}
    driver.get(local_page.url)

    fetched = fetch_in_page(BrowserSession(RecordingContext(), driver), ["/files/a", "/files/b"])

    assert [f.data for f in fetched] == [b"\x89PNG fake", b"\x00\x01"]
    assert fetched[0].content_type == "image/png"
    assert fetched[1].content_type is None


def test_a_failed_fetch_raises(driver, local_page):
    driver.get(local_page.url)

    with pytest.raises(RuntimeError, match="HTTP 404"):
        fetch_in_page(BrowserSession(RecordingContext(), driver), ["/files/missing"])


@pytest.mark.parametrize(
    ("content_type", "name", "saved_type"),
    [
        ("image/png; charset=binary", "piece.png", "image/png"),
        (None, "piece.bin", "application/octet-stream"),
        ("application/x-unheard-of", "piece.bin", "application/octet-stream"),
    ],
    ids=["known-type", "no-type", "unknown-type"],
)
def test_a_saved_file_is_named_by_its_type(content_type, name, saved_type):
    ctx = RecordingContext()

    assert save_fetched(ctx, "piece", FetchedFile(b"data", content_type)) == name
    assert ctx.artifacts == [(name, saved_type, b"data")]
