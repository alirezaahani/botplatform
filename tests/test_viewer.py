"""The live view: proxy, viewer_connected event, warning and the Watch live link rules.

The upstream is a fake noVNC server, and `live.worker_base_url` points at it.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from starlette.websockets import WebSocketDisconnect

from botplatform.db import Base, BotRecord, Run, RunEvent, session_factory
from botplatform.web import live
from botplatform.web.app import app
from tests.fake_demo.server import _Server


def fake_novnc() -> FastAPI:
    novnc = FastAPI()

    @novnc.get("/vnc.html")
    def page() -> HTMLResponse:
        return HTMLResponse("<title>fake noVNC</title>")

    @novnc.websocket("/websockify")
    async def echo(websocket: WebSocket) -> None:
        await websocket.accept(subprotocol="binary")
        while True:
            await websocket.send_bytes(b"echo:" + await websocket.receive_bytes())

    return novnc


@pytest.fixture(scope="module")
def upstream() -> Iterator[str]:
    server = _Server(fake_novnc())
    server.start()
    yield server.origin
    server.stop()


@pytest.fixture
def client(upstream: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    seen: list[str] = []
    monkeypatch.setattr(
        live, "worker_base_url", lambda worker_id: seen.append(worker_id) or upstream
    )
    sessions = session_factory()
    Base.metadata.create_all(sessions.kw["bind"])
    with sessions.begin() as session:
        session.execute(delete(Run))
        session.execute(delete(BotRecord))
        session.add(BotRecord(id="arcaptcha", name="ARCaptcha", modes=["headless", "headful"]))
    with TestClient(app) as test_client:
        test_client.worker_ids = seen  # type: ignore[attr-defined]
        yield test_client


def make_run(
    mode: str = "headful", status: str = "running", worker_id: str | None = "worker-1"
) -> uuid.UUID:
    with session_factory().begin() as session:
        run = Run(bot_id="arcaptcha", mode=mode, status=status, worker_id=worker_id)
        session.add(run)
        session.flush()
        return run.id


def event_types(run_id: uuid.UUID) -> list[str]:
    with session_factory()() as session:
        return list(session.scalars(select(RunEvent.type).where(RunEvent.run_id == run_id)))


def test_static_files_come_from_the_runs_worker(client: TestClient) -> None:
    run_id = make_run()
    response = client.get(f"/runs/{run_id}/live/vnc.html")
    assert response.status_code == 200
    assert "fake noVNC" in response.text
    assert client.worker_ids == ["worker-1"]


def test_live_redirects_to_novnc_through_the_proxy(client: TestClient) -> None:
    run_id = make_run()
    response = client.get(f"/runs/{run_id}/live", follow_redirects=False)
    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith(f"/runs/{run_id}/live/vnc.html?")
    # noVNC 1.6 resolves `path` against the page URL, so a custom path would double the prefix.
    assert "path=" not in location


def test_websocket_carries_bytes_both_ways(client: TestClient) -> None:
    run_id = make_run()
    with client.websocket_connect(
        f"/runs/{run_id}/live/websockify", subprotocols=["binary"]
    ) as socket:
        socket.send_bytes(b"hello")
        assert socket.receive_bytes() == b"echo:hello"
        socket.send_bytes(b"again")
        assert socket.receive_bytes() == b"echo:again"


def test_each_connection_adds_one_viewer_connected_event(client: TestClient) -> None:
    run_id = make_run()
    path = f"/runs/{run_id}/live/websockify"
    assert event_types(run_id) == []
    for expected in (1, 2):
        with client.websocket_connect(path, subprotocols=["binary"]) as socket:
            socket.send_bytes(b"x")
            socket.receive_bytes()
        assert event_types(run_id) == ["viewer_connected"] * expected


def test_warning_shows_only_after_a_viewer_connected(client: TestClient) -> None:
    run_id = make_run()
    warning = "A viewer was connected during this run, so the result may be human-assisted."
    assert warning not in client.get(f"/runs/{run_id}").text
    with client.websocket_connect(f"/runs/{run_id}/live/websockify", subprotocols=["binary"]):
        pass
    assert warning in client.get(f"/runs/{run_id}").text


@pytest.mark.parametrize(
    ("kwargs", "status_code"),
    [
        ({"mode": "headless"}, 409),
        ({"status": "success"}, 409),
        ({"status": "queued", "worker_id": None}, 409),
    ],
)
def test_proxy_refuses_runs_that_cannot_be_watched(
    client: TestClient, kwargs: dict, status_code: int
) -> None:
    run_id = make_run(**kwargs)
    assert client.get(f"/runs/{run_id}/live", follow_redirects=False).status_code == status_code
    assert client.get(f"/runs/{run_id}/live/vnc.html").status_code == status_code
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"/runs/{run_id}/live/websockify"),
    ):
        pass
    assert event_types(run_id) == []


def test_proxy_refuses_an_unknown_run(client: TestClient) -> None:
    assert client.get(f"/runs/{uuid.uuid4()}/live", follow_redirects=False).status_code == 404


@pytest.mark.parametrize(
    ("kwargs", "link"),
    [
        ({}, True),
        ({"status": "queued", "worker_id": "worker-1"}, True),
        ({"mode": "headless"}, False),
        ({"status": "success"}, False),
        ({"status": "queued", "worker_id": None}, False),
    ],
)
def test_watch_live_link_rules(client: TestClient, kwargs: dict, link: bool) -> None:
    run_id = make_run(**kwargs)
    assert (f'href="/runs/{run_id}/live"' in client.get(f"/runs/{run_id}").text) is link


def test_run_history_filter_accepts_all_and_rejects_unknown(client: TestClient) -> None:
    make_run()
    assert client.get("/runs?status=").status_code == 200  # the form's "All" option
    assert client.get("/runs?status=queued").status_code == 200
    assert client.get("/runs?status=nonsense").status_code == 400
