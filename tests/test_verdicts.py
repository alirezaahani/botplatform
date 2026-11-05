"""How a run is judged from what the browser saw. Pure decisions: no Chrome."""

import pytest

from botplatform.bots.arcaptcha.page import verify_login
from botplatform.bots.arcaptcha.traffic import classify_create
from botplatform.contract import BotResult, Status

BLOCKED = BotResult(Status.BLOCKED, "captcha_blocked")
UNSOLVED = BotResult(Status.BLOCKED, "challenge_unsolved")
NO_ID = BotResult(Status.FAILED, "missing_challenge_id")
UNKNOWN_TYPE = "unknown_captcha_type"
OK = "You are logged in successfully!"


def create(captcha_type: str | None, challenge_id: str | None = "id-1") -> dict:
    """One decoded `create` answer, as the run keeps it."""
    return {"captcha_type": captcha_type, "challenge_id": challenge_id}


def reason(result: BotResult | None) -> tuple[Status, str | None] | None:
    return None if result is None else (result.status, result.reason)


@pytest.mark.parametrize(
    ("creates", "create_request_failed", "expected"),
    [
        pytest.param([create("accept")], False, None, id="accepted"),
        pytest.param([create("cookie")], False, None, id="accepted-by-cookie"),
        pytest.param([create("block")], False, reason(BLOCKED), id="blocked"),
        pytest.param([create("block", None)], False, reason(BLOCKED), id="blocked-without-an-id"),
        pytest.param(
            [create("puzzle"), create("block")], False, reason(BLOCKED), id="block-after-a-puzzle"
        ),
        pytest.param([create("puzzle")], False, reason(UNSOLVED), id="puzzle"),
        pytest.param([create("question")], False, reason(UNSOLVED), id="question"),
        pytest.param([create("2fa")], False, reason(UNSOLVED), id="two-factor"),
        pytest.param(
            [create("puzzle"), create("accept", None)],
            False,
            None,
            id="the-puzzle-was-passed-so-the-first-id-counts",
        ),
        pytest.param([create("accept", None)], False, reason(NO_ID), id="accepted-without-an-id"),
        pytest.param([create(None, None)], False, reason(NO_ID), id="body-nobody-could-decode"),
        pytest.param([], True, (Status.ERROR, "create_request_failed"), id="request-failed"),
        pytest.param([create("accept")], True, None, id="a-later-failure-does-not-undo-an-answer"),
        pytest.param([create("hologram")], False, (Status.ERROR, UNKNOWN_TYPE), id="unknown-type"),
    ],
)
def test_what_the_create_answers_say_about_the_run(creates, create_request_failed, expected):
    assert reason(classify_create(creates, create_request_failed)) == expected


def test_an_unknown_captcha_type_is_named_so_it_can_be_looked_into():
    result = classify_create([create("hologram")], False)
    assert result is not None
    assert result.error == "captcha_type='hologram'"


@pytest.mark.parametrize(
    ("http_status", "body", "toast", "confirmed"),
    [
        pytest.param(200, {"msg": OK}, {"kind": "success", "text": OK}, True, id="both-agree"),
        pytest.param(
            200,
            {"msg": OK},
            {"kind": "success", "text": f"  {OK}  Bye"},
            True,
            id="toast-says-more",
        ),
        pytest.param(
            401,
            {"msg": "Wrong password"},
            {"kind": "error", "text": "Wrong password"},
            False,
            id="refused",
        ),
        pytest.param(401, {"msg": OK}, {"kind": "success", "text": OK}, False, id="green-on-a-401"),
        pytest.param(200, {"msg": OK}, {"kind": "error", "text": OK}, False, id="red-on-a-200"),
        pytest.param(
            200, {"msg": OK}, {"kind": "success", "text": "Other"}, False, id="other-text"
        ),
        pytest.param(200, {"msg": OK}, {"kind": "none", "text": ""}, False, id="no-toast"),
        pytest.param(200, {}, {"kind": "success", "text": OK}, False, id="no-message"),
        pytest.param(200, None, {"kind": "success", "text": OK}, False, id="body-not-json"),
    ],
)
def test_a_login_counts_only_when_the_response_and_the_toast_agree(
    http_status, body, toast, confirmed
):
    result = verify_login(http_status, body, toast)

    assert (result is None) is confirmed
    if not confirmed:
        assert reason(result) == (Status.FAILED, "verification_failed")
