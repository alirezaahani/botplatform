"""What the `create` answers say about a run. A pure decision: no Chrome."""

import pytest

from botplatform.bots.arcaptcha.checkbox import classify_create
from botplatform.bots.arcaptcha.session import Create
from botplatform.contract import BotResult, Status

BLOCKED = BotResult(Status.BLOCKED, "captcha_blocked")
UNSOLVED = BotResult(Status.BLOCKED, "challenge_unsolved")
NO_ID = BotResult(Status.FAILED, "missing_challenge_id")
UNKNOWN_TYPE = "unknown_captcha_type"


def create(captcha_type: str | None, challenge_id: str | None = "id-1") -> Create:
    """One decoded `create` answer, as the run keeps it."""
    return Create(captcha_type, challenge_id)


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
