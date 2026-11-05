"""The run, step by step: open and tick, let the challenge deal with a puzzle, log in, judge."""

from botplatform.bots.arcaptcha import page
from botplatform.bots.arcaptcha.challenge import Challenge, GiveUp
from botplatform.bots.arcaptcha.session import Session
from botplatform.bots.arcaptcha.traffic import types
from botplatform.bots.utils.browser import describe, screenshot
from botplatform.contract import BotResult, Status


def run_flow(session: Session, challenge: Challenge | None = None) -> BotResult:
    challenge = challenge or GiveUp()
    ctx = session.ctx
    earlier = page.open_and_tick(session)
    if (
        earlier
        and earlier.reason == "challenge_unsolved"
        and types(session.creates)[-1:] == ["puzzle"]
    ):
        earlier = challenge.resolve(session)
    screenshot(session, "after-click")
    # Decision 3b: the login is always attempted, but it can never upgrade an earlier failure.
    try:
        verdict = page.log_in(session)
    except Exception as error:
        if not earlier:
            raise
        ctx.event("login_failed", {"error": describe(error)})
        screenshot(session, "login-failed")
        return earlier
    screenshot(session, "after-login")
    # Both steps found nothing wrong, so this is the only place a run can succeed.
    if session.solved:
        return earlier or verdict or BotResult(Status.SUCCESS, "solved")
    return earlier or verdict or BotResult(Status.SUCCESS)
