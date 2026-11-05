"""Reading network responses through Chrome's DevTools events. The platform core never imports it."""

import base64
import json
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import WebDriverException

from botplatform.bots.utils.browser import describe


@dataclass(frozen=True)
class CapturedResponse:
    """A finished network response. `body` is None if Chrome could not give it to us."""

    name: str
    url: str
    status: int
    body: bytes | None
    body_error: str | None = None
    request_body: bytes | None = None
    request_body_error: str | None = None


class ResponseWatcher:
    """Collects finished responses for chosen URLs, from Chrome's DevTools network events.

    Call `poll()` regularly. Responses come back in the order they finished. Only requests
    whose method is in `methods` count (POST by default): a cross-origin call also logs a CORS
    preflight for the same URL, which is ignored because its method is `OPTIONS` (Chrome 156
    gives it the type `Other`). Request bodies are read too, so a login request's password is
    captured.
    """

    def __init__(
        self,
        driver: webdriver.Chrome,
        matchers: dict[str, Callable[[str], bool]],
        *,
        methods: Collection[str] = ("POST",),
    ):
        self._driver = driver
        self._matchers = matchers
        self._methods = methods
        self._request_bodies: dict[str, bytes] = {}  # request id -> body
        self._pending: dict[str, tuple[str, str, int]] = {}  # request id -> name, url, status
        self._tracked: dict[str, str] = {}  # request id -> name, for counted requests
        # Matching requests that were not counted, such as CORS preflights, for the run's record.
        self.ignored: list[dict[str, str | None]] = []
        self.started: list[str] = []  # names of counted requests, in the order they started
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
                self._request_bodies.pop(request_id, None)
                if request_id in self._tracked:
                    self.failed.append(self._tracked.pop(request_id))
        return found

    def _see_request(self, request_id: str, params: dict) -> None:
        request = params["request"]
        name = next((n for n, matches in self._matchers.items() if matches(request["url"])), None)
        if name is None:
            return
        if request["method"] in self._methods:
            self._tracked[request_id] = name
            self.started.append(name)
            body = self._inline_request_body(request)
            if body is not None:
                self._request_bodies[request_id] = body
        else:
            self.ignored.append(
                {"name": name, "method": request["method"], "type": params.get("type")}
            )

    @staticmethod
    def _inline_request_body(request: dict) -> bytes | None:
        """The body if Chrome put it in the event itself. Large or binary ones are fetched later."""
        entries = request.get("postDataEntries")
        if entries and all("bytes" in entry for entry in entries):
            return b"".join(base64.b64decode(entry["bytes"]) for entry in entries)
        if isinstance(request.get("postData"), str):
            return request["postData"].encode("utf-8")
        return None

    def _read_request_body(self, request_id: str) -> tuple[bytes | None, str | None]:
        if request_id in self._request_bodies:
            return self._request_bodies.pop(request_id), None
        try:
            result = self._driver.execute_cdp_cmd(
                "Network.getRequestPostData", {"requestId": request_id}
            )
        except WebDriverException as error:
            return None, describe(error)
        data = result["postData"]
        return (base64.b64decode(data) if result.get("base64Encoded") else data.encode()), None

    def _read_body(self, request_id: str, name: str, url: str, status: int) -> CapturedResponse:
        request_body, request_error = self._read_request_body(request_id)
        try:
            result = self._driver.execute_cdp_cmd(
                "Network.getResponseBody", {"requestId": request_id}
            )
        except WebDriverException as error:
            return CapturedResponse(
                name, url, status, None, describe(error), request_body, request_error
            )
        body = result["body"]
        data = base64.b64decode(body) if result.get("base64Encoded") else body.encode("utf-8")
        return CapturedResponse(name, url, status, data, None, request_body, request_error)


def path_endswith(suffix: str) -> Callable[[str], bool]:
    """A matcher for URLs whose path (the query string is ignored) ends with `suffix`."""
    return lambda url: url.split("?")[0].endswith(suffix)


def exchange_record(
    response: CapturedResponse, decode: Callable[[bytes], Any] = json.loads
) -> dict[str, Any]:
    """A decoded request and response, for the run's record.

    Each side that has no body, or fails to decode, is None with a `<side>_note` that says why.
    """
    record: dict[str, Any] = {"http_status": response.status}
    for side, data, error in (
        ("request", response.request_body, response.request_body_error),
        ("response", response.body, response.body_error),
    ):
        if data is None:
            record[side] = None
            record[f"{side}_note"] = f"no body: {error}"
            continue
        try:
            record[side] = decode(data)
        except Exception as failure:  # noqa: BLE001 - a failed decode must not crash a run
            record[side] = None
            record[f"{side}_note"] = f"decode failed: {describe(failure)}"
            record[f"{side}_text"] = data.decode("utf-8", errors="replace")[:500]
    return record
