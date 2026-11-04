"""A fake ARCaptcha demo site, started inside pytest.

Two uvicorn servers on 127.0.0.1 with random ports, so the API is truly cross-origin: the page
and `/api/login` live on one origin, and `/arcaptcha/api/create` (with CORS) on the other.
Tests set the outcomes on a `FakeDemo` object before the bot runs.

It only proves our own assumptions about the real site. Success here is not evidence that the
real site would accept the bot.
"""

import asyncio
import json
import socket
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from tests.fake_demo.encoder import encode

PAGE = (Path(__file__).parent / "page.html").read_text()
CHALLENGE_ID = "123456789012345678901234567890"


@dataclass
class Reply:
    """What an endpoint sends. `action` is `reply`, `hang` (until teardown) or `drop`.

    `json` is obfuscated for `create` unless `plain` is set. `raw` bytes are sent as they are.
    """

    status: int = 201
    json: Any = None
    raw: bytes | None = None
    plain: bool = False
    action: str = "reply"


def create_reply(captcha_type: str, challenge_id: str | None = CHALLENGE_ID, **content: Any):
    """A `create` reply shaped like the real API. `challenge_id=None` leaves the ID out."""
    if challenge_id is not None:
        content = {"challenge_id": challenge_id, "site_key": "d6ggpvy684", **content}
    return Reply(json={"status": "OK", "captcha_type": captcha_type, "content": content})


class _Server:
    def __init__(self, app: FastAPI) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.origin = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        config = uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=2)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True
        )

    def start(self) -> None:
        self.thread.start()
        while not self.server.started:
            if not self.thread.is_alive():
                raise RuntimeError("the fake server did not start")
            threading.Event().wait(0.02)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)
        self.sock.close()


class FakeDemo:
    def __init__(self) -> None:
        # What the tests configure
        self.page: Reply = Reply(action="reply")  # `hang` makes the page load never finish
        self.checkbox = True
        self.second_create = False  # the page sends a second `create` after the first answer
        self.alert_on_click: str | None = None
        self.toast: dict[str, Any] = {"none": False, "kind": None, "text": None}
        self.creates: list[Reply] = [create_reply("accept")]  # the last one repeats
        # What the page's own answer button posts to `answer`. The last reply repeats.
        self.answers: list[Reply] = [Reply(json={"status": "OK", "accepted": True})]
        self.login = Reply(status=200, json={"msg": "You are logged in successfully!"})
        # What the tests inspect
        self.create_requests = 0
        self.answer_requests: list[dict[str, Any]] = []
        self.logins: list[dict[str, Any]] = []
        self._release = threading.Event()  # set on teardown, to free every hanging request

        self._api = _Server(self._api_app())
        self._site = _Server(self._site_app())
        self.url = self._site.origin + "/"
        self.api_origin = self._api.origin

    def start(self) -> None:
        self._api.start()
        self._site.start()

    def stop(self) -> None:
        self._release.set()
        self._site.stop()
        self._api.stop()

    def stop_api(self) -> None:
        """Close the API origin's port, so the page's `create` call is refused."""
        self._api.stop()

    async def _hang(self) -> None:
        while not self._release.is_set():
            await asyncio.sleep(0.05)

    async def _respond(self, reply: Reply, *, obfuscate: bool) -> Response:
        if reply.action == "hang":
            await self._hang()
            return Response(status_code=503)
        if reply.raw is not None:
            body, media = reply.raw, "application/octet-stream"
        elif obfuscate and not reply.plain:
            body, media = encode(reply.json), "application/octet-stream"
        else:
            body, media = json.dumps(reply.json).encode(), "application/json"
        if reply.action == "drop":
            # Headers and half a body go out, then the stream breaks: Chrome logs loadingFailed.
            async def broken() -> AsyncIterator[bytes]:
                yield body[: max(1, len(body) // 2)]
                await asyncio.sleep(0.05)
                raise RuntimeError("connection dropped on purpose")

            return StreamingResponse(broken(), status_code=reply.status, media_type=media)
        return Response(body, status_code=reply.status, media_type=media)

    def _site_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/")
        async def index() -> Response:
            if self.page.action == "hang":
                await self._hang()
            config = {
                "api_origin": self.api_origin,
                "second_create": self.second_create,
                "alert_on_click": self.alert_on_click,
                "toast": self.toast,
            }
            html = PAGE.replace("__CONFIG__", json.dumps(config))
            if not self.checkbox:
                html = html.replace('<div id="input-checkbox"', '<div id="not-the-checkbox"')
            return HTMLResponse(html)

        @app.post("/api/login")
        async def login(request: Request) -> Response:
            self.logins.append(await request.json())
            return await self._respond(self.login, obfuscate=False)

        return app

    def _api_app(self) -> FastAPI:
        app = FastAPI()
        # The page is on another origin, so the browser sends an OPTIONS preflight first.
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"http://127\.0\.0\.1:\d+",
            allow_methods=["POST"],
            allow_headers=["content-type"],
        )

        @app.post("/arcaptcha/api/create")
        async def create() -> Response:
            reply = self.creates[min(self.create_requests, len(self.creates) - 1)]
            self.create_requests += 1
            return await self._respond(reply, obfuscate=True)

        @app.post("/arcaptcha/api/answer")
        async def answer(request: Request) -> Response:
            self.answer_requests.append(await request.json())
            reply = self.answers[min(len(self.answer_requests), len(self.answers)) - 1]
            return await self._respond(reply, obfuscate=True)

        return app
