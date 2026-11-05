"""The ARCaptcha demo bots: `ArcaptchaBot`, built from a `BotSpec`, and the registered instances."""

from botplatform.bots.arcaptcha.bot import (
    BASELINE_BOT,
    BASELINE_SPEC,
    PROFILE_BOTS,
    SOLVER_BOTS,
    ArcaptchaBot,
)
from botplatform.bots.arcaptcha.session import StepTimeouts

__all__ = [
    "BASELINE_BOT",
    "BASELINE_SPEC",
    "PROFILE_BOTS",
    "SOLVER_BOTS",
    "ArcaptchaBot",
    "StepTimeouts",
]
