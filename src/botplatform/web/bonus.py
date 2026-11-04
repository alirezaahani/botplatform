"""The bonus report: for each bot and mode, how often did the site answer `create` without a block.

The run history is the evidence store, so this only reads `runs` and `run_events`.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, exists, select
from sqlalchemy.orm import Session

from botplatform.db import BotRecord, Run, RunEvent
from botplatform.stats import wilson_interval
from botplatform.web.deps import DbSession

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
CAPTCHA_TYPES = ("block", "puzzle", "accept", "cookie", "question", "2fa", "none")
NOT_BLOCKED = (
    'The create request was answered with any captcha type other than "block". The rate is '
    "not blocked runs divided by runs whose create answer has a type. Runs with no answer "
    'or no type ("none") are counted in the table but not in the rate.'
)


@dataclass
class Row:
    bot: str
    mode: str
    runs: int = 0
    excluded: int = 0  # runs a person watched, left out of everything below
    outcomes: Counter = field(default_factory=Counter)  # "status/reason" -> runs
    types: Counter = field(default_factory=Counter)
    with_challenge_id: int = 0
    success: int = 0

    @property
    def typed(self) -> int:
        return sum(n for name, n in self.types.items() if name != "none")

    @property
    def not_blocked(self) -> int:
        return self.typed - self.types["block"]

    @property
    def rate(self) -> float | None:
        return self.not_blocked / self.typed if self.typed else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson_interval(self.not_blocked, self.typed)


def _first_event(field_name: str):
    """The first `create_response` value of a run: a later `create` must not count twice."""
    return (
        select(RunEvent.data[field_name].as_string())
        .where(RunEvent.run_id == Run.id, RunEvent.type == "create_response")
        .order_by(RunEvent.id)
        .limit(1)
        .scalar_subquery()
    )


def collect(session: Session, since: datetime | None, bot: str | None) -> list[Row]:
    viewed = exists().where(RunEvent.run_id == Run.id, RunEvent.type == "viewer_connected")
    query = (
        select(
            Run.bot_id,
            Run.mode,
            Run.status,
            Run.reason,
            Run.challenge_id,
            _first_event("captcha_type"),
            viewed,
        )
        .select_from(Run)
        .join(BotRecord, BotRecord.id == Run.bot_id)
    )
    # Newest bot first, like the Bots page. Alphabetically headful sorts first, so headless
    # before headful needs the explicit case.
    query = query.order_by(
        BotRecord.position.desc(), Run.bot_id, case((Run.mode == "headless", 0), else_=1), Run.mode
    )
    if since is not None:
        query = query.where(Run.queued_at >= since)
    if bot:
        query = query.where(Run.bot_id == bot)
    rows: dict[tuple[str, str], Row] = {}
    for bot_id, mode, status, reason, challenge_id, captcha_type, viewer in session.execute(query):
        row = rows.setdefault((bot_id, mode), Row(bot_id, mode))
        if viewer:
            row.excluded += 1
            continue
        row.runs += 1
        row.outcomes[f"{status}/{reason}" if reason else status] += 1
        row.success += status == "success"
        row.with_challenge_id += challenge_id is not None
        known = captcha_type in CAPTCHA_TYPES
        row.types[captcha_type if known else ("none" if captcha_type is None else "other")] += 1
    return list(rows.values())


def percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def rate_text(row: Row) -> str:
    interval = row.interval
    if interval is None:
        return "-"
    return f"{percent(row.rate)} ({percent(interval[0])} to {percent(interval[1])})"


def outcome_text(counter: Counter) -> str:
    return ", ".join(f"{name} {n}" for name, n in sorted(counter.items())) or "-"


def type_text(row: Row) -> str:
    names = [*CAPTCHA_TYPES, "other"]
    return ", ".join(f"{name} {row.types[name]}" for name in names if row.types[name]) or "-"


def markdown(rows: list[Row], since: datetime | None, bot: str | None, now: datetime) -> str:
    excluded = sum(row.excluded for row in rows)
    lines = [
        "# Bonus report: blocked or not",
        "",
        f"- Generated at: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"- Filters: since {since.isoformat() if since else 'none'}, bot {bot or 'all'}",
        "- Every recorded run that matches the filters is included, except runs with a "
        f"`viewer_connected` event (a person may have helped): {excluded} excluded"
        + (
            " (" + ", ".join(f"{r.bot} {r.mode} {r.excluded}" for r in rows if r.excluded) + ")"
            if excluded
            else ""
        ),
        f'- "Not blocked": {NOT_BLOCKED} Interval: 95% Wilson.',
        "",
    ]
    if not rows:
        return "\n".join([*lines, "No runs.", ""])
    header = (
        "| Bot | Mode | Runs | Outcomes | create types | Not blocked | Rate (95% CI) "
        "| With challenge ID | Success | Excluded |"
    )
    lines += [header, "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r.bot} | {r.mode} | {r.runs} | {outcome_text(r.outcomes)} | {type_text(r)} "
            f"| {r.not_blocked} of {r.typed} | {rate_text(r)} | {r.with_challenge_id} "
            f"| {r.success} | {r.excluded} |"
        )
    return "\n".join([*lines, ""])


def parse_since(value: str) -> datetime | None:
    if not value:
        return None
    try:
        since = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"'since' is not an ISO datetime: {value}") from None
    return since if since.tzinfo else since.replace(tzinfo=UTC)


@router.get("/bonus", response_class=HTMLResponse)
def bonus_page(
    request: Request, session: DbSession, since: str = "", bot: str = ""
) -> HTMLResponse:
    parsed = parse_since(since)
    rows = collect(session, parsed, bot or None)
    return templates.TemplateResponse(
        request,
        "bonus.html",
        {
            "rows": rows,
            "since": since,
            "bot": bot,
            "excluded": sum(row.excluded for row in rows),
            "rate_text": rate_text,
            "outcome_text": outcome_text,
            "type_text": type_text,
            "not_blocked_definition": NOT_BLOCKED,
        },
    )


@router.get("/bonus.md")
def bonus_markdown(session: DbSession, since: str = "", bot: str = "") -> Response:
    parsed = parse_since(since)
    rows = collect(session, parsed, bot or None)
    text = markdown(rows, parsed, bot or None, datetime.now(UTC))
    return Response(text, media_type="text/markdown; charset=utf-8")
