"""Test-only encoder: the inverse of `botplatform.bots.arcaptcha.codec`.

It gives the fake `create` endpoint the same obfuscated bodies as the real widget API.
"""

import json
import os
import random
from typing import Any


def _next_key(state: list[int]) -> int:
    state[0] = (state[0] + state[1]) & 255
    state[1] = (state[1] ^ state[2]) & 255
    state[2] = (state[2] + state[3]) & 255
    state[3] = (state[3] ^ state[0]) & 255
    return (state[0] + state[3]) & 255


def encode_bytes(data: bytes, seed: bytes) -> bytes:
    """The cipher itself. `data` must already end with its padding length byte."""
    state = list(seed)
    feedback = 90
    out = bytearray(seed)
    for byte_in in data:
        mixed = ((byte_in ^ _next_key(state)) + feedback) & 255
        byte = ((mixed << 3) | (mixed >> 5)) & 255
        out.append(byte)
        feedback = byte
    return bytes(out)


def encode(value: Any, seed: bytes | None = None, padding: int | None = None) -> bytes:
    """Obfuscate a JSON value. The seed and the padding are random unless given."""
    seed = seed if seed is not None else os.urandom(4)
    padding = padding if padding is not None else random.randint(0, 12)
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return encode_bytes(body + bytes(padding) + bytes([padding]), seed)
