"""The bot registry. To register a bot, import it here and add it to `BOTS`."""

from botplatform.bots.arcaptcha import (
    PROFILE_BOTS,
    SOLVER_BOTS,
    ArcaptchaAssistedBot,
    ArcaptchaBot,
)
from botplatform.bots.example import ExampleBot
from botplatform.contract import Bot

# Append new bots at the END: the order is the order they were added, and the web UI shows the
# last one first. `PROFILE_BOTS` follow `PROFILES`, which is also append-only.
BOTS: list[type[Bot]] = [
    ExampleBot,
    ArcaptchaBot,
    *PROFILE_BOTS,
    ArcaptchaAssistedBot,
    *SOLVER_BOTS,
]
