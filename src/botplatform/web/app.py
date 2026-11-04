"""The web UI. It reads and queues runs through the database, and never imports bot code."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from botplatform.contract import ACTIVE_STATUSES, Status
from botplatform.db import BotRecord, Run, RunArtifact, RunEvent
from botplatform.web import live
from botplatform.web.deps import DbSession

HERE = Path(__file__).parent
PAGE_SIZE = 50
STILL_QUEUED_AFTER = timedelta(minutes=1)

app = FastAPI(title="Bot Platform")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
app.include_router(live.router)
templates = Jinja2Templates(directory=HERE / "templates")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def home() -> RedirectResponse:
    return RedirectResponse("/bots")


@app.get("/bots", response_class=HTMLResponse)
def list_bots(request: Request, session: DbSession) -> HTMLResponse:
    bots = session.scalars(select(BotRecord).where(BotRecord.active).order_by(BotRecord.name)).all()
    return templates.TemplateResponse(request, "bots.html", {"bots": bots})


@app.post("/bots/{bot_id}/runs")
def launch_run(bot_id: str, mode: Annotated[str, Form()], session: DbSession) -> RedirectResponse:
    bot = session.get(BotRecord, bot_id)
    if bot is None or not bot.active:
        raise HTTPException(404, f"No active bot '{bot_id}'")
    if mode not in bot.modes:
        raise HTTPException(400, f"'{bot_id}' does not support mode '{mode}'")
    run = Run(bot_id=bot_id, mode=mode)
    session.add(run)
    session.commit()
    return RedirectResponse(f"/runs/{run.id}", status_code=303)


@app.get("/runs", response_class=HTMLResponse)
def list_runs(
    request: Request,
    session: DbSession,
    status: Status | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> HTMLResponse:
    query = select(Run)
    count_query = select(func.count()).select_from(Run)
    if status is not None:
        query = query.where(Run.status == status)
        count_query = count_query.where(Run.status == status)
    runs = session.scalars(
        query.order_by(Run.queued_at.desc()).limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)
    ).all()
    total = session.scalar(count_query) or 0
    return templates.TemplateResponse(
        request,
        "runs.html",
        {
            "runs": runs,
            "statuses": list(Status),
            "selected_status": status,
            "page": page,
            "has_next": page * PAGE_SIZE < total,
            "any_active": any(run.status in ACTIVE_STATUSES for run in runs),
        },
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: uuid.UUID, request: Request, session: DbSession) -> HTMLResponse:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "No such run")
    events = session.scalars(
        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id)
    ).all()
    artifacts = session.execute(
        select(RunArtifact.id, RunArtifact.name, RunArtifact.content_type)
        .where(RunArtifact.run_id == run_id)
        .order_by(RunArtifact.created_at)
    ).all()
    still_queued = (
        run.status == Status.QUEUED and datetime.now(UTC) - run.queued_at > STILL_QUEUED_AFTER
    )
    return templates.TemplateResponse(
        request,
        "run.html",
        {
            "run": run,
            "events": events,
            "artifacts": artifacts,
            "active": run.status in ACTIVE_STATUSES,
            "still_queued": still_queued,
        },
    )


@app.get("/artifacts/{artifact_id}")
def artifact(artifact_id: uuid.UUID, session: DbSession) -> Response:
    item = session.get(RunArtifact, artifact_id)
    if item is None:
        raise HTTPException(404, "No such artifact")
    return Response(item.data, media_type=item.content_type)
