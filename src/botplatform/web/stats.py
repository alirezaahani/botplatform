"""The stats page: for each bot and mode, how many finished runs ended in each status."""

from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, exists, select
from sqlalchemy.orm import Session

from botplatform.contract import ACTIVE_STATUSES, Status
from botplatform.db import BotRecord, Run, RunEvent
from botplatform.stats import wilson_interval
from botplatform.web.deps import DbSession

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@dataclass
class Row:
    bot: str
    mode: str
    counts: dict[str, int] = field(default_factory=dict)  # status -> runs nobody watched
    watched: int = 0

    @property
    def runs(self) -> int:
        return sum(self.counts.values())

    @property
    def success(self) -> int:
        return self.counts.get(Status.SUCCESS, 0)


def collect(session: Session) -> list[Row]:
    viewed = exists().where(RunEvent.run_id == Run.id, RunEvent.type == "viewer_connected")
    query = (
        select(Run.bot_id, Run.mode, Run.status, viewed)
        .join(BotRecord, BotRecord.id == Run.bot_id)
        .where(Run.status.not_in([s.value for s in ACTIVE_STATUSES]))
        # Newest bot first, like the Bots page. Alphabetically headful sorts first, so headless
        # before headful needs the explicit case.
        .order_by(
            BotRecord.position.desc(),
            Run.bot_id,
            case((Run.mode == "headless", 0), else_=1),
            Run.mode,
        )
    )
    rows: dict[tuple[str, str], Row] = {}
    for bot_id, mode, status, watched in session.execute(query):
        row = rows.setdefault((bot_id, mode), Row(bot_id, mode))
        if watched:
            row.watched += 1
        else:
            row.counts[status] = row.counts.get(status, 0) + 1
    return list(rows.values())


def percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def rate_text(row: Row) -> str:
    interval = wilson_interval(row.success, row.runs)
    if interval is None:
        return "-"
    return f"{percent(row.success / row.runs)} ({percent(interval[0])} to {percent(interval[1])})"


@router.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request, session: DbSession) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "rows": collect(session),
            "columns": (
                Status.SUCCESS,
                Status.BLOCKED,
                Status.FAILED,
                Status.TIMEOUT,
                Status.ERROR,
            ),
            "rate_text": rate_text,
        },
    )
