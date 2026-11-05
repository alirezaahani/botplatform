"""Network responses: reading them off the watcher, recording them and classifying `create`s."""

import json
from typing import Any

from botplatform.bots.arcaptcha.codec import decode_body
from botplatform.bots.arcaptcha.puzzle import capture_puzzle
from botplatform.bots.arcaptcha.session import Session
from botplatform.bots.selenium_support import CapturedResponse
from botplatform.contract import BotResult, Status

CHALLENGE_TYPES = {"puzzle", "question", "2fa"}
ACCEPTED_TYPES = {"accept", "cookie"}


def drain(session: Session) -> bool:
    """Read new network responses. Each `create` is recorded the moment it is seen."""
    # Reading the network log never notices a JS `alert()`, and an open alert freezes the
    # page. Any other driver command raises when one is open, which `do` then handles.
    session.driver.title  # noqa: B018
    seen_create = False
    for response in session.watcher.poll():
        if response.name == "login":
            session.logins.append(response)
        elif response.name == "answer":
            record = exchange_record(response)
            session.answer_records.append(record)
            session.ctx.event("answer_request", record)
        else:
            handle_create(session, response)
            seen_create = True
    if session.pending_puzzle is not None:
        # Once per poll, for the latest puzzle: if two `create`s arrive together, the page
        # shows only the second puzzle, so the first has nothing left to capture.
        (challenge_id,), session.pending_puzzle = session.pending_puzzle, None
        capture_puzzle(session, challenge_id)
    return seen_create or bool(session.logins)


def handle_create(session: Session, response: CapturedResponse) -> None:
    info: dict[str, Any] = {"http_status": response.status, "captcha_type": None}
    challenge_id = None
    if response.body is None:
        info["body_error"] = response.body_error
    else:
        try:
            decoded = decode_body(response.body)
            info["captcha_type"] = decoded.get("captcha_type")
            challenge_id = (decoded.get("content") or {}).get("challenge_id")
        except (ValueError, AttributeError, TypeError) as error:
            info["decode_error"] = type(error).__name__
    if not isinstance(challenge_id, str) or not challenge_id:
        challenge_id = None
    session.ctx.event("create_request", exchange_record(response))
    session.creates.append({"captcha_type": info["captcha_type"], "challenge_id": challenge_id})
    info["has_challenge_id"] = challenge_id is not None
    if challenge_id:
        session.ctx.record_challenge_id(challenge_id)
    session.capture = None
    session.ctx.event("create_response", info)
    session.pending_puzzle = (challenge_id,) if info["captcha_type"] == "puzzle" else None


def exchange_record(response: CapturedResponse) -> dict[str, Any]:
    """A decoded request and response. The `create` request holds the browser signals sent."""
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
            record[side] = decode_body(data)
        except Exception as failure:  # noqa: BLE001 - a failed decode must not crash a run
            record[side] = None
            record[f"{side}_note"] = f"decode failed: {type(failure).__name__}"
            record[f"{side}_raw_length"] = len(data)
    return record


def types(creates: list[dict[str, Any]]) -> list[str]:
    """The types of the `create` answers we could decode. Only those decide the outcome."""
    return [c["captcha_type"] for c in creates if c["captcha_type"] is not None]


def classify_create(creates: list[dict[str, Any]], create_failed: bool) -> BotResult | None:
    """The failure the `create` answers show, or None if the widget accepted us."""
    if not creates and create_failed:
        return BotResult(
            Status.ERROR, "create_request_failed", "The create request failed before a response"
        )
    seen = types(creates)
    if "block" in seen:
        return BotResult(Status.BLOCKED, "captcha_blocked")
    if not any(create["challenge_id"] for create in creates):
        return BotResult(Status.FAILED, "missing_challenge_id")
    latest = seen[-1] if seen else None
    if latest in CHALLENGE_TYPES:
        return BotResult(Status.BLOCKED, "challenge_unsolved")
    if latest not in ACCEPTED_TYPES:
        # Never guess: a type we have not seen cannot be treated as an accepted checkbox.
        return BotResult(Status.ERROR, "unknown_captcha_type", f"captcha_type={latest!r}")
    return None


def classify(session: Session) -> BotResult | None:
    return classify_create(session.creates, "create" in session.watcher.failed)


def json_body(response: CapturedResponse) -> Any:
    try:
        return json.loads(response.body.decode("utf-8")) if response.body else None
    except ValueError:
        return None


def body_text(response: CapturedResponse) -> Any:
    if response.body is None:
        return {"unreadable": response.body_error}
    parsed = json_body(response)
    if parsed is not None:
        return parsed
    return response.body.decode("utf-8", errors="replace")[:500]
