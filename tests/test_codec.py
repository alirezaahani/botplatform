import json

import pytest

from botplatform.bots.arcaptcha import ArcaptchaBot
from botplatform.bots.arcaptcha_codec import decode_body
from botplatform.bots.example import ExampleBot
from tests.fake_demo.encoder import encode, encode_bytes


@pytest.mark.parametrize("padding", [0, 1, 7, 12])
def test_round_trip_including_non_ascii(padding):
    value = {"captcha_type": "accept", "content": {"message": "héllo ✓ فارسی", "n": [1, 2]}}
    assert decode_body(encode(value, padding=padding)) == value


def test_plain_json_is_accepted():
    assert decode_body(b'{"captcha_type": "block"}') == {"captcha_type": "block"}


def test_too_short_body_is_rejected():
    with pytest.raises(ValueError, match="too short"):
        decode_body(b"\x01\x02\x03\x04")


def test_bad_padding_is_rejected():
    # The last plain byte says 200 bytes of padding, but only a few bytes exist.
    body = encode_bytes(json.dumps({"a": 1}).encode() + bytes([200]), seed=b"\x01\x02\x03\x04")
    with pytest.raises(ValueError, match="padding"):
        decode_body(body)


def test_garbage_is_rejected():
    with pytest.raises(ValueError):
        decode_body(b"this is not a captcha body at all")


def test_declared_modes():
    assert ArcaptchaBot.modes == ["headless"]
    assert ExampleBot.modes == ["direct"]
