"""The live view: web proxies the noVNC page and its WebSocket to the worker running the run."""

import asyncio
import uuid

import httpx
import websockets
from fastapi import APIRouter, HTTPException, Response, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from botplatform.contract import ACTIVE_STATUSES
from botplatform.db import Run, RunEvent, session_factory
from botplatform.web.deps import DbSession

VIEWER_PORT = 6080

router = APIRouter()


def worker_base_url(worker_id: str) -> str:
    """Where a worker's viewer listens. A worker's ID is its container hostname."""
    return f"http://{worker_id}:{VIEWER_PORT}"


def viewer_url(session: Session, run_id: uuid.UUID) -> str:
    """The worker's viewer address for a run, or an HTTP error saying why there is none."""
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "No such run")
    if run.mode != "headful":
        raise HTTPException(409, "Only headful runs can be watched live")
    if run.status not in ACTIVE_STATUSES:
        raise HTTPException(409, "This run is not active, so there is nothing to watch")
    if not run.worker_id:
        raise HTTPException(409, "No worker has picked up this run yet")
    return worker_base_url(run.worker_id)


def novnc_page(run_id: uuid.UUID) -> RedirectResponse:
    """noVNC finds its WebSocket at `path`, so point that at our proxy."""
    base = f"runs/{run_id}/live"
    return RedirectResponse(
        f"/{base}/vnc.html?path={base}/websockify&autoconnect=true&resize=scale"
    )


@router.get("/runs/{run_id}/live")
def live(run_id: uuid.UUID, session: DbSession) -> RedirectResponse:
    viewer_url(session, run_id)
    return novnc_page(run_id)


@router.get("/runs/{run_id}/live/{path:path}")
async def live_file(run_id: uuid.UUID, path: str, session: DbSession) -> Response:
    base = viewer_url(session, run_id)
    if not path:
        return novnc_page(run_id)
    try:
        async with httpx.AsyncClient() as client:
            upstream = await client.get(f"{base}/{path}")
    except httpx.HTTPError as error:
        raise HTTPException(502, f"The worker's viewer is not reachable: {error}") from error
    return Response(
        upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


@router.websocket("/runs/{run_id}/live/websockify")
async def live_socket(websocket: WebSocket, run_id: uuid.UUID, session: DbSession) -> None:
    try:
        base = viewer_url(session, run_id)
    except HTTPException:
        await websocket.close(code=1008)
        return
    session.close()  # do not hold a connection for as long as someone watches
    # noVNC asks for the `binary` subprotocol, and websockify only answers if we repeat it.
    protocols = websocket.scope.get("subprotocols", [])
    try:
        async with websockets.connect(
            base.replace("http", "ws", 1) + "/websockify",
            subprotocols=protocols or None,
            max_size=None,
        ) as upstream:
            await websocket.accept(subprotocol=upstream.subprotocol)
            await run_in_threadpool(record_viewer, run_id)
            await pump(websocket, upstream)
    except (OSError, websockets.WebSocketException):
        await websocket.close(code=1011)


def record_viewer(run_id: uuid.UUID) -> None:
    """Note on the run that someone could take part, for the warning on its page."""
    with session_factory().begin() as session:
        session.add(RunEvent(run_id=run_id, type="viewer_connected"))


async def pump(browser: WebSocket, worker: websockets.ClientConnection) -> None:
    """Copy messages both ways until either side closes."""

    async def to_worker() -> None:
        while (message := await browser.receive())["type"] == "websocket.receive":
            await worker.send(message.get("bytes") or message.get("text") or b"")

    async def to_browser() -> None:
        async for data in worker:
            if isinstance(data, bytes):
                await browser.send_bytes(data)
            else:
                await browser.send_text(data)

    tasks = [asyncio.create_task(to_worker()), asyncio.create_task(to_browser())]
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
