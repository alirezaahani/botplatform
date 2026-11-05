"""Network responses: reading them off the watcher and recording them."""

from typing import Any

from botplatform.bots.arcaptcha.codec import decode_body
from botplatform.bots.arcaptcha.puzzle_capture import capture_puzzle
from botplatform.bots.arcaptcha.session import Session
from botplatform.bots.utils.browser import raise_if_alert_open
from botplatform.bots.utils.network import CapturedResponse, exchange_record


def drain(session: Session) -> bool:
    """Read new network responses. Each `create` is recorded the moment it is seen."""
    raise_if_alert_open(session.driver)  # the network log alone would not notice one
    seen_create = False
    for response in session.watcher.poll():
        if response.name == "login":
            record = exchange_record(response, decode_body)
            session.logins.append(record)
            session.ctx.event("login_request", record)
        elif response.name == "answer":
            record = exchange_record(response, decode_body)
            session.answer_records.append(record)
            session.ctx.event("answer_request", record)
        else:
            handle_create(session, response)
            seen_create = True
    if session.puzzle_pending:
        # Once per poll, for the latest puzzle: if two `create`s arrive together, the page
        # shows only the second puzzle, so the first has nothing left to capture.
        session.puzzle_pending = False
        capture_puzzle(session, session.creates[-1]["challenge_id"])
    return seen_create or bool(session.logins)


def handle_create(session: Session, response: CapturedResponse) -> None:
    record = exchange_record(response, decode_body)
    decoded = record["response"]
    info: dict[str, Any] = {"http_status": response.status, "captcha_type": None}
    if response.body is None:
        info["body_error"] = response.body_error
    elif "response_note" in record:
        info["decode_error"] = record["response_note"]
    if isinstance(decoded, dict):
        info["captcha_type"] = decoded.get("captcha_type")
    match decoded:
        case {"content": {"challenge_id": str() as found}} if found:
            challenge_id = found
        case _:
            challenge_id = None
    session.ctx.event("create_request", record)
    session.creates.append({"captcha_type": info["captcha_type"], "challenge_id": challenge_id})
    info["has_challenge_id"] = challenge_id is not None
    if challenge_id:
        session.ctx.record_challenge_id(challenge_id)
    session.capture = None
    session.ctx.event("create_response", info)
    session.puzzle_pending = info["captcha_type"] == "puzzle"
