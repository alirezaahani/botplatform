"""The live view: web proxies the noVNC page and its WebSocket to the worker running the run."""

import asyncio
import uuid

import httpx
import websockets
from fastapi import APIRouter, HTTPException, Response, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from botplatform.contract import ACTIVE_STATUSES
from botplatform.db import Run, RunEvent, SessionLocal

VIEWER_PORT = 6080
VIEWER_RECHECK_SECONDS = 2.0

router = APIRouter()


def worker_base_url(worker_id: str) -> str:
    """Where a worker's viewer listens. A worker's ID is its container hostname."""
    return f"http://{worker_id}:{VIEWER_PORT}"


def why_not_watchable(run: Run) -> str | None:
    """Why `run` cannot be watched live, or None if it can. The run page shows its link by this."""
    if run.mode != "headful":
        return "Only headful runs can be watched live"
    if run.status not in ACTIVE_STATUSES:
        return "This run is not active, so there is nothing to watch"
    if not run.worker_id:
        return "No worker has picked up this run yet"
    return None


def viewer_url(run_id: uuid.UUID) -> str:
    """The worker's viewer address for a run, or an HTTP error saying why there is none."""
    with SessionLocal() as session:
        run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "No such run")
    reason = why_not_watchable(run)
    if reason or not run.worker_id:  # `why_not_watchable` checks the worker too; this tells pyright
        raise HTTPException(409, reason)
    return worker_base_url(run.worker_id)


def novnc_page(run_id: uuid.UUID) -> RedirectResponse:
    """noVNC resolves its default `path=websockify` against the page URL, which is our proxy."""
    return RedirectResponse(f"/runs/{run_id}/live/vnc.html?autoconnect=true&resize=scale")


@router.get("/runs/{run_id}/live")
def live(run_id: uuid.UUID) -> RedirectResponse:
    viewer_url(run_id)
    return novnc_page(run_id)


@router.get("/runs/{run_id}/live/{path:path}")
async def live_file(run_id: uuid.UUID, path: str) -> Response:
    base = await run_in_threadpool(viewer_url, run_id)
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
async def live_socket(websocket: WebSocket, run_id: uuid.UUID) -> None:
    try:
        base = await run_in_threadpool(viewer_url, run_id)
    except HTTPException:
        await websocket.close(code=1008)
        return
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
            await pump(websocket, upstream, run_id)
    except (OSError, websockets.WebSocketException):
        await websocket.close(code=1011)


def record_viewer(run_id: uuid.UUID) -> None:
    """Note on the run that someone could take part, for the warning on its page."""
    with SessionLocal.begin() as session:
        session.add(RunEvent(run_id=run_id, type="viewer_connected"))


def run_is_active(run_id: uuid.UUID) -> bool:
    with SessionLocal() as session:
        run = session.get(Run, run_id)
        return run is not None and run.status in ACTIVE_STATUSES


async def pump(browser: WebSocket, worker: websockets.ClientConnection, run_id: uuid.UUID) -> None:
    """Copy messages both ways until either side closes or the run ends."""

    async def to_worker() -> None:
        while (message := await browser.receive())["type"] == "websocket.receive":
            await worker.send(message.get("bytes") or message.get("text") or b"")

    async def to_browser() -> None:
        async for data in worker:
            if isinstance(data, bytes):
                await browser.send_bytes(data)
            else:
                await browser.send_text(data)

    async def until_run_ends() -> None:
        # The display belongs to the worker, so the next run would otherwise be watched unwarned.
        while True:
            await asyncio.sleep(VIEWER_RECHECK_SECONDS)
            if not await run_in_threadpool(run_is_active, run_id):
                return

    tasks = [
        asyncio.create_task(to_worker()),
        asyncio.create_task(to_browser()),
        ending := asyncio.create_task(until_run_ends()),
    ]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if ending in done:
        await browser.close(code=1000)
        await worker.close()
