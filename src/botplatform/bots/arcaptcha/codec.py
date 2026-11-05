"""Decodes the ARCaptcha widget's `create` response body.

Ported from module 51723 in widget.arcaptcha.ir/dist/checkbox.js. The first 4 bytes are a random
seed, so there is no secret key. The widget also accepts plain JSON, so we try that as well.
"""

import json
from typing import Any

_INITIAL_FEEDBACK = 90


def _next_key(state: list[int]) -> int:
    state[0] = (state[0] + state[1]) & 255
    state[1] = (state[1] ^ state[2]) & 255
    state[2] = (state[2] + state[3]) & 255
    state[3] = (state[3] ^ state[0]) & 255
    return (state[0] + state[3]) & 255


def _decode_obfuscated(data: bytes) -> Any:
    if len(data) < 5:
        raise ValueError("body is too short to be obfuscated")
    state = list(data[:4])
    feedback = _INITIAL_FEEDBACK
    plain = bytearray()
    for byte in data[4:]:
        key = _next_key(state)
        rotated = ((byte >> 3) | (byte << 5)) & 255
        plain.append(((rotated - feedback) & 255) ^ key)
        feedback = byte
    padding = plain[-1]
    if padding > len(plain) - 1:
        raise ValueError("invalid padding length")
    return json.loads(plain[: len(plain) - 1 - padding].decode("utf-8"))


def decode_body(data: bytes) -> Any:
    """Return the JSON value in a response body, or raise ValueError."""
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:  # UnicodeDecodeError is a ValueError too
        return _decode_obfuscated(data)
