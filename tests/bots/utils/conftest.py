"""Setup for the helper tests: a plain local page with no ARCaptcha in it, and a Chrome driver."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from selenium import webdriver

from botplatform.bots.utils.browser import chrome
from tests.local_server import LocalServer

BLANK = "<!doctype html><title>local page</title>"


class LocalPage:
    """A page to load in Chrome. Set `html` and `files` before loading `url`.

    `/api/<name>` answers GET and POST with 201 and what it got, from any origin.
    """

    def __init__(self) -> None:
        self.html = BLANK
        self.files: dict[str, tuple[bytes, str | None]] = {}  # name -> body, content type
        app = FastAPI()
        app.add_middleware(
            CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
        )

        @app.get("/")
        def index() -> HTMLResponse:
            return HTMLResponse(self.html)

        @app.api_route("/api/{name}", methods=["GET", "POST"])
        async def api(name: str, request: Request) -> JSONResponse:
            got = (await request.body()).decode()
            return JSONResponse({"name": name, "got": got}, status_code=201)

        @app.get("/files/{name}")
        def file(name: str) -> Response:
            if name not in self.files:
                raise HTTPException(404)
            data, content_type = self.files[name]
            return Response(data, media_type=content_type)

        self.server = LocalServer(app)
        self.origin = self.server.origin
        self.url = self.origin + "/"


@pytest.fixture
def local_page() -> Iterator[LocalPage]:
    page = LocalPage()
    page.server.start()
    yield page
    page.server.stop()


@pytest.fixture
def driver() -> Iterator[webdriver.Chrome]:
    """Headless Chrome with the baseline profile."""
    with chrome(headless=True) as started:
        yield started
