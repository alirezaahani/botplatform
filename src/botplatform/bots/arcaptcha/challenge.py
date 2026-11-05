"""A bot's reaction to a challenge: a strategy object on its spec."""

from typing import Protocol

from botplatform.bots.arcaptcha.session import Session
from botplatform.contract import BotResult, Status


class Challenge(Protocol):
    """What a bot does when the widget shows a challenge it has to pass."""

    def resolve(self, session: Session) -> BotResult | None:
        """The latest `create` is a puzzle and was not accepted: try to deal with it.

        Return a final BotResult to end the challenge phase with that outcome (the login still
        runs after, but cannot upgrade it), or None if the challenge was passed.
        """
        ...


class GiveUp:
    """The default: do nothing, so the run ends as blocked / challenge_unsolved."""

    def resolve(self, session: Session) -> BotResult | None:
        return BotResult(Status.BLOCKED, "challenge_unsolved")
