"""The run, step by step: open and tick, solve a puzzle if there is one, log in, judge."""

from botplatform.bots.arcaptcha import page, solver
from botplatform.bots.arcaptcha.session import Session, screenshot
from botplatform.bots.arcaptcha.timeouts import StepTimeout
from botplatform.bots.arcaptcha.traffic import types
from botplatform.contract import BotResult, Status


def run_flow(session: Session, solve_with: tuple[str, str] | None = None) -> BotResult:
    try:
        return _run(session, solve_with)
    except StepTimeout as timeout:
        screenshot(session, f"timeout-{timeout.step}")
        return BotResult(Status.TIMEOUT, timeout.step, f"Timed out in step '{timeout.step}'")
    except Exception:
        screenshot(session, "error")
        raise


def _run(session: Session, solve_with: tuple[str, str] | None) -> BotResult:
    ctx = session.ctx
    ctx.event("browser_profile", session.profile.settings())
    earlier = page.open_and_tick(session)
    earlier = _solve_if_puzzle(session, earlier, solve_with)
    screenshot(session, "after-click")
    # Decision 3b: the login is always attempted, but it can never upgrade an earlier failure.
    try:
        verdict = page.log_in(session)
    except StepTimeout as timeout:
        if earlier:
            ctx.event("login_timeout", {"step": timeout.step})
            screenshot(session, "login-timeout")
            return earlier
        raise
    except Exception as error:
        if not earlier:
            raise
        ctx.event("login_error", {"type": type(error).__name__})
        screenshot(session, "login-error")
        return earlier
    screenshot(session, "after-login")
    # Both steps found nothing wrong, so this is the only place a run can succeed.
    if session.solved:
        return earlier or verdict or BotResult(Status.SUCCESS, "solved")
    return earlier or verdict or BotResult(Status.SUCCESS)


def _solve_if_puzzle(
    session: Session, result: BotResult | None, solve_with: tuple[str, str] | None
) -> BotResult | None:
    """THE place where the flow hands over to a solver, for a bot that has one."""
    unsolved = BotResult(Status.BLOCKED, "challenge_unsolved")
    if solve_with and result == unsolved and types(session.creates)[-1] == "puzzle":
        return solver.run_solver(session, solve_with)
    return result
