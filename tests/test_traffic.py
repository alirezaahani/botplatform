"""Recording what the site sent. Bad bodies are noted in the record and never raise. No Chrome."""

import pytest

from botplatform.bots.arcaptcha.traffic import body_text, exchange_record
from botplatform.bots.selenium_support import CapturedResponse


def response(body: bytes | None, error: str | None = None, **kwargs) -> CapturedResponse:
    return CapturedResponse("create", "u", 201, body, error, **kwargs)


def test_a_readable_exchange_is_decoded_on_both_sides():
    record = exchange_record(response(b'{"captcha_type": "accept"}', request_body=b'{"a": 1}'))

    assert (record["request"], record["response"]) == ({"a": 1}, {"captcha_type": "accept"})
    assert not [key for key in record if key.endswith("_note")]


@pytest.mark.parametrize(
    ("captured", "side", "note_starts_with"),
    [
        pytest.param(response(None, "WebDriverException: gone"), "response", "no body: WebDriver"),
        pytest.param(response(b"\x01\x02\x03"), "response", "decode failed"),
        pytest.param(
            response(b"{}", request_body=b"\x01\x02", request_body_error=None),
            "request",
            "decode failed",
        ),
    ],
    ids=["no-response-body", "undecodable-response", "undecodable-request"],
)
def test_a_body_that_cannot_be_read_is_noted_and_does_not_raise(captured, side, note_starts_with):
    record = exchange_record(captured)

    assert record[side] is None
    assert record[f"{side}_note"].startswith(note_starts_with)
    assert record["http_status"] == 201


@pytest.mark.parametrize(
    ("captured", "expected"),
    [
        pytest.param(response(b'{"msg": "ok"}'), {"msg": "ok"}, id="json-is-parsed"),
        pytest.param(response(b"<html>oops</html>"), "<html>oops</html>", id="text-is-kept"),
        pytest.param(response(b"x" * 900), "x" * 500, id="long-text-is-cut"),
        pytest.param(response(None, "gone"), {"unreadable": "gone"}, id="no-body-says-why"),
    ],
)
def test_the_login_response_is_recorded_as_json_when_it_is_json_and_as_text_otherwise(
    captured, expected
):
    assert body_text(captured) == expected
