"""What an ARCaptcha bot does when the widget shows a puzzle: a `Challenge` on the bot."""

from abc import ABC, abstractmethod

from botplatform.bots.arcaptcha.session import Session
from botplatform.contract import BotResult, Status


class Challenge(ABC):
    """Subclass this to deal with a puzzle, and pass an instance to `ArcaptchaBot`."""

    @abstractmethod
    def resolve(self, session: Session) -> BotResult | None:
        """The latest `create` is a puzzle and was not accepted: try to deal with it.

        Return a final BotResult to end the challenge phase with that outcome (the login still
        runs after, but cannot upgrade it), or None if the challenge was passed.
        """


class GiveUp(Challenge):
    """The default: do nothing, so the run ends as blocked / challenge_unsolved."""

    def resolve(self, session: Session) -> BotResult | None:
        return BotResult(Status.BLOCKED, "challenge_unsolved")
