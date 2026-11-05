"""The run, step by step: open and tick, let the challenge deal with a puzzle, log in, judge."""

from botplatform.bots.arcaptcha import page
from botplatform.bots.arcaptcha.challenge import Challenge, GiveUp
from botplatform.bots.arcaptcha.session import Session, screenshot
from botplatform.bots.arcaptcha.timeouts import StepTimeout
from botplatform.bots.arcaptcha.traffic import types
from botplatform.bots.selenium_support import describe
from botplatform.contract import BotResult, Status

UNSOLVED = BotResult(Status.BLOCKED, "challenge_unsolved")


def run_flow(session: Session, challenge: Challenge | None = None) -> BotResult:
    try:
        return _run(session, challenge or GiveUp())
    except StepTimeout as timeout:
        screenshot(session, f"timeout-{timeout.step}")
        return BotResult(Status.TIMEOUT, timeout.step, f"Timed out in step '{timeout.step}'")
    except Exception:
        screenshot(session, "error")
        raise


def _run(session: Session, challenge: Challenge) -> BotResult:
    ctx = session.ctx
    ctx.event("browser_profile", session.profile.settings())
    earlier = page.open_and_tick(session)
    if earlier == UNSOLVED and types(session.creates)[-1:] == ["puzzle"]:
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
