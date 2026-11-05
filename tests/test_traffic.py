"""Response classification and records. Pure functions: no Chrome."""

import json

import pytest

from botplatform.bots.arcaptcha.traffic import (
    body_text,
    classify_create,
    exchange_record,
    json_body,
    types,
)
from botplatform.bots.selenium_support import CapturedResponse
from botplatform.contract import BotResult, Status


def create(captcha_type: str | None, challenge_id: str | None = "id-1") -> dict:
    return {"captcha_type": captcha_type, "challenge_id": challenge_id}


def response(body: bytes | None, error: str | None = None, **kwargs) -> CapturedResponse:
    return CapturedResponse("create", "u", 201, body, error, **kwargs)


@pytest.mark.parametrize(
    ("creates", "failed", "expected"),
    [
        ([], True, BotResult(Status.ERROR, "create_request_failed")),
        ([create("block")], False, BotResult(Status.BLOCKED, "captcha_blocked")),
        ([create("puzzle"), create("block")], False, BotResult(Status.BLOCKED, "captcha_blocked")),
        ([create("accept", None)], False, BotResult(Status.FAILED, "missing_challenge_id")),
        ([create(None, None)], False, BotResult(Status.FAILED, "missing_challenge_id")),
        ([create("puzzle")], False, BotResult(Status.BLOCKED, "challenge_unsolved")),
        ([create("question")], False, BotResult(Status.BLOCKED, "challenge_unsolved")),
        ([create("2fa")], False, BotResult(Status.BLOCKED, "challenge_unsolved")),
        ([create("accept")], False, None),
        ([create("cookie")], False, None),
        ([create("puzzle"), create("accept", None)], False, None),
        ([create("weird")], False, BotResult(Status.ERROR, "unknown_captcha_type")),
        ([create(None)], False, BotResult(Status.ERROR, "unknown_captcha_type")),
        # A failed request after a good response does not undo the response.
        ([create("accept")], True, None),
    ],
)
def test_classify_create(creates, failed, expected):
    result = classify_create(creates, failed)
    if expected is None:
        assert result is None
    else:
        assert (result.status, result.reason) == (expected.status, expected.reason)


def test_unknown_type_is_named_in_the_error():
    assert classify_create([create("weird")], False).error == "captcha_type='weird'"


def test_types_skips_undecodable_creates():
    assert types([create("puzzle"), create(None), create("accept")]) == ["puzzle", "accept"]


def test_record_for_a_missing_body():
    record = exchange_record(response(None, "WebDriverException: gone"))
    assert record["http_status"] == 201
    assert record["response"] is None
    assert record["response_note"] == "no body: WebDriverException: gone"
    assert record["request"] is None
    assert record["request_note"] == "no body: None"


def test_record_for_a_body_that_does_not_decode():
    record = exchange_record(response(b"\x01\x02\x03"))
    assert record["response"] is None
    assert record["response_note"].startswith("decode failed")
    assert record["response_raw_length"] == 3


def test_record_for_a_good_body():
    record = exchange_record(response(b'{"captcha_type": "accept"}', request_body=b'{"a": 1}'))
    assert record["response"] == {"captcha_type": "accept"}
    assert record["request"] == {"a": 1}
    assert "response_note" not in record


@pytest.mark.parametrize(
    ("body", "expected"),
    [(b'{"msg": "ok"}', {"msg": "ok"}), (b"not json", None), (b"", None), (None, None)],
)
def test_json_body(body, expected):
    assert json_body(response(body)) == expected


def test_body_text_of_json_is_the_parsed_value():
    assert body_text(response(json.dumps({"msg": "ok"}).encode())) == {"msg": "ok"}


def test_body_text_of_non_json_is_the_text_cut_to_500():
    assert body_text(response(b"<html>oops</html>")) == "<html>oops</html>"
    assert body_text(response(b"x" * 900)) == "x" * 500
    assert body_text(response(b"\xff\xfe")) == "��"


def test_body_text_of_an_unreadable_body_gives_the_reason():
    assert body_text(response(None, "gone")) == {"unreadable": "gone"}
