"""The ARCaptcha demo bots: `ArcaptchaBot` and its registered instances."""

from botplatform.bots.arcaptcha.bot import (
    BASELINE_BOT,
    PROFILE_BOTS,
    SOLVER_BOTS,
    ArcaptchaBot,
)
from botplatform.bots.arcaptcha.session import StepTimeouts

__all__ = [
    "BASELINE_BOT",
    "PROFILE_BOTS",
    "SOLVER_BOTS",
    "ArcaptchaBot",
    "StepTimeouts",
]
