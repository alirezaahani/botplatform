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
import struct
import threading
import zlib
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


def tiny_png(width: int, height: int, grey: int) -> bytes:
    """A valid grey PNG of the given size."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + bytes([grey]) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


BACKGROUND_PNG = tiny_png(8, 4, 200)
PIECE_PNG = tiny_png(3, 3, 50)


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


@dataclass(frozen=True)
class Puzzle:
    """A puzzle the fake serves: both images and the piece's `top` in px."""

    background: bytes
    piece: bytes
    top: int = 20


@dataclass
class Toast:
    """What the page shows after the login response. `kind` and `text` default to what the
    response says (green and its message for 200, red otherwise)."""

    show: bool = True
    kind: str | None = None
    text: str | None = None


class FakeDemo:
    """The fake site. Set the replies (`creates`, `login`, `toast`) or call a scenario method, run
    the bot, then inspect `logins`, `answers` and `create_requests`."""

    def __init__(self) -> None:
        self.creates: list[Reply] = [create_reply("accept")]  # the last one repeats
        self.login = Reply(status=200, json={"msg": "You are logged in successfully!"})
        self.toast = Toast()
        # What the tests inspect
        self.create_requests = 0
        self.answer_requests: list[dict[str, Any]] = []
        self.logins: list[dict[str, Any]] = []
        # Page behavior, changed through the scenario methods
        self._page_hangs = False
        self._has_checkbox = True
        self._second_create = False
        self._images_missing = False
        self._alert_on_click: str | None = None
        self._puzzle = Puzzle(BACKGROUND_PNG, PIECE_PNG)
        self._slider: float | None = None  # piece left = handle left * this; None: no handle
        self._ignore_presses = 0
        self._target: int | None = None
        self._release = threading.Event()  # set on teardown, to free every hanging request

        self._api = _Server(self._api_app())
        self._site = _Server(self._site_app())
        self.url = self._site.origin + "/"
        self.api_origin = self._api.origin

    # -- Scenarios -------------------------------------------------------------------------------

    def hang_page(self) -> None:
        """The page request never finishes."""
        self._page_hangs = True

    def remove_checkbox(self) -> None:
        self._has_checkbox = False

    def break_puzzle_images(self) -> None:
        """The puzzle's image URLs answer 404."""
        self._images_missing = True

    def send_second_create(self) -> None:
        """After the first answer, the page asks for a second `create` at once."""
        self._second_create = True

    def alert_on_click(self, text: str) -> None:
        self._alert_on_click = text

    def serve_puzzles(
        self,
        puzzle: Puzzle,
        *,
        target: int,
        ids: list[str],
        ignore_presses: int = 0,
    ) -> None:
        """Every `create` is a puzzle (one id each, the last repeats) with a draggable handle.

        An answer equal to `target` is accepted and any other is rejected with a new puzzle. The
        handle ignores its first `ignore_presses` presses, like a widget that is not ready yet.
        """
        self.creates = [create_reply("puzzle", challenge_id=cid) for cid in ids]
        self._puzzle = puzzle
        self._slider = 1.0
        self._target = target
        self._ignore_presses = ignore_presses

    @property
    def answers(self) -> list[Any]:
        """The `answer` of every answer request, in order."""
        return [request.get("answer") for request in self.answer_requests]

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
            if self._page_hangs:
                await self._hang()
            config = {
                "api_origin": self.api_origin,
                "second_create": self._second_create,
                "alert_on_click": self._alert_on_click,
                "slider": self._slider,
                "puzzle": None if self._slider is None else {"top": self._puzzle.top},
                "ignore_presses": self._ignore_presses,
                "toast": {
                    "none": not self.toast.show,
                    "kind": self.toast.kind,
                    "text": self.toast.text,
                },
            }
            html = PAGE.replace("__CONFIG__", json.dumps(config))
            if not self._has_checkbox:
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
            allow_methods=["POST", "GET"],
            allow_headers=["content-type"],
        )

        @app.post("/arcaptcha/api/create")
        async def create() -> Response:
            reply = self.creates[min(self.create_requests, len(self.creates) - 1)]
            self.create_requests += 1
            return await self._respond(reply, obfuscate=True)

        @app.get("/arcaptcha/api/puzzles/{challenge_id}/undefined/{part}")
        async def puzzle_image(challenge_id: str, part: str) -> Response:
            if self._images_missing:
                return Response(status_code=404)
            png = self._puzzle.piece if part == "piece" else self._puzzle.background
            return Response(png, media_type="image/png")

        @app.post("/arcaptcha/api/answer")
        async def answer(request: Request) -> Response:
            body = await request.json()
            self.answer_requests.append(body)
            accepted = self._target is not None and body.get("answer") == self._target
            reply = Reply(json={"status": "OK", "success": accepted})
            return await self._respond(reply, obfuscate=True)

        return app
