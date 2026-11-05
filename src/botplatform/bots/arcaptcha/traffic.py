"""Network responses: reading them off the watcher, recording them and classifying `create`s."""

from typing import Any

from botplatform.bots.arcaptcha.codec import decode_body
from botplatform.bots.arcaptcha.puzzle import capture_puzzle
from botplatform.bots.arcaptcha.session import Session
from botplatform.bots.selenium_support import CapturedResponse, describe
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
            record = exchange_record(response)
            session.logins.append(record)
            session.ctx.event("login_request", record)
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
    record = exchange_record(response)
    decoded = record["response"]
    info: dict[str, Any] = {"http_status": response.status, "captcha_type": None}
    if response.body is None:
        info["body_error"] = response.body_error
    elif "response_note" in record:
        info["decode_error"] = record["response_note"]
    challenge_id = None
    if isinstance(decoded, dict):
        info["captcha_type"] = decoded.get("captcha_type")
        content = decoded.get("content")
        challenge_id = content.get("challenge_id") if isinstance(content, dict) else None
    if not isinstance(challenge_id, str) or not challenge_id:
        challenge_id = None
    session.ctx.event("create_request", record)
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
            record[f"{side}_note"] = f"decode failed: {describe(failure)}"
            record[f"{side}_text"] = data.decode("utf-8", errors="replace")[:500]
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
