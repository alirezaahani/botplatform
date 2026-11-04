"""The bot registry. To register a bot, import it here and add it to `BOTS`."""

from botplatform.bots.arcaptcha import PROFILE_BOTS, ArcaptchaAssistedBot, ArcaptchaBot
from botplatform.bots.example import ExampleBot
from botplatform.contract import Bot

BOTS: list[type[Bot]] = [ExampleBot, ArcaptchaBot, ArcaptchaAssistedBot, *PROFILE_BOTS]
