"""The ARCaptcha demo bots: one `ArcaptchaBot` class, built from a `BotSpec` for each variant."""

from botplatform.bots.arcaptcha.challenge import Challenge, GiveUp
from botplatform.bots.arcaptcha.core import BASELINE_BOT, PROFILE_BOTS, SOLVER_BOTS, ArcaptchaBot
from botplatform.bots.arcaptcha.session import StepTimeouts
from botplatform.bots.arcaptcha.solver import SliderSolver
from botplatform.bots.arcaptcha.spec import BASELINE_SPEC, BotSpec, profile_spec, solver_spec

__all__ = [
    "BASELINE_BOT",
    "BASELINE_SPEC",
    "PROFILE_BOTS",
    "SOLVER_BOTS",
    "ArcaptchaBot",
    "BotSpec",
    "Challenge",
    "GiveUp",
    "SliderSolver",
    "StepTimeouts",
    "profile_spec",
    "solver_spec",
]
