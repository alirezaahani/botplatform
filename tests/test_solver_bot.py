"""The solver bots against the fake demo, which accepts an answer equal to the known target."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from botplatform.bots import BOTS
from botplatform.bots.arcaptcha import SOLVER_BOTS, ArcaptchaBot
from botplatform.contract import Status
from botplatform.profiles import ALL_SIGNALS, ALL_SIGNALS_HEADLESS
from botplatform.solver import gap
from tests.conftest import FAST, RecordingContext, assert_no_password
from tests.fake_demo.server import create_reply

DIR = Path(__file__).parent / "fixtures" / "solver"
ROW = json.loads((DIR / "manifest.json").read_text())[0]
TARGET = ROW["cv_target"]
IDS = [f"{i:030d}" for i in range(1, 6)]
SOLVE = replace(FAST, puzzle_ready=6, puzzle_images=4, answer_settle=2, solve_attempts=3)
BY_ID = {bot.id: bot for bot in SOLVER_BOTS}
BOT_IDS = [
    "arcaptcha-solver-cv-linear",
    "arcaptcha-solver-cv-eased",
    "arcaptcha-solver-silhouette-linear",
    "arcaptcha-solver-silhouette-eased",
]


@pytest.fixture
def solve(fake, credentials):
    fake.slider = 1.0
    fake.puzzle = ((DIR / ROW["background"]).read_bytes(), (DIR / ROW["piece"]).read_bytes(), 60)
    fake.target = TARGET
    fake.creates = [create_reply("puzzle", challenge_id=cid) for cid in IDS]

    def run(bot_id="arcaptcha-solver-cv-linear", timeouts=SOLVE):
        ctx = RecordingContext()
        result = ArcaptchaBot(BY_ID[bot_id].spec, url=fake.url, timeouts=timeouts).run(ctx)
        assert_no_password(type("O", (), {"result": result, "ctx": ctx})())
        return result, ctx

    return run


def finder_returning(monkeypatch, *targets):
    values = list(targets)

    def finder(background, piece, top):
        return values.pop(0) if len(values) > 1 else values[0]

    monkeypatch.setitem(gap.FINDERS, "cv", finder)


@pytest.mark.parametrize("bot_id", BOT_IDS)
def test_both_bots_solve_on_the_first_attempt(solve, fake, bot_id):
    result, ctx = solve(bot_id)

    assert (result.status, result.reason) == (Status.SUCCESS, "solved")
    assert [a["answer"] for a in fake.answer_requests] == [TARGET]
    assert len(fake.logins) == 1
    mover = bot_id.rsplit("-", 1)[1]
    finder = bot_id.split("-")[2]
    assert ctx.one("solve_started")["mover"] == mover
    attempt = ctx.one("solve_attempt")
    assert attempt["n"] == 1
    assert attempt["challenge_id"] == IDS[0]
    assert attempt["finder"] == finder
    assert attempt["mover"] == mover
    assert attempt["target_x"] == attempt["dx"] == TARGET
    assert attempt["stuck_retries"] == 0
    assert attempt["outcome"] == "accepted"
    assert attempt["handle_left"] == TARGET
    assert attempt["piece_left"] == TARGET
    assert attempt["steps"] == 8 if mover == "linear" else attempt["steps"] >= 25
    assert 0.5 <= attempt["duration"] <= 1.5
    assert ctx.one("solve_finished")["reason"] == "solved"
    assert ctx.one("puzzle_captured")["challenge_id"] == IDS[0]


def test_a_wrong_first_target_is_rejected_and_the_second_is_accepted(solve, fake, monkeypatch):
    finder_returning(monkeypatch, 50, TARGET)
    result, ctx = solve()

    assert (result.status, result.reason) == (Status.SUCCESS, "solved")
    attempts = ctx.of("solve_attempt")
    assert [a["outcome"] for a in attempts] == ["rejected", "accepted"]
    assert [a["target_x"] for a in attempts] == [50, TARGET]
    assert [a["challenge_id"] for a in attempts] == IDS[:2]
    assert [a["answer"] for a in fake.answer_requests] == [50, TARGET]


def test_three_rejections_end_blocked_as_solve_failed(solve, fake, monkeypatch):
    finder_returning(monkeypatch, 50)
    result, ctx = solve("arcaptcha-solver-cv-eased")

    assert (result.status, result.reason) == (Status.BLOCKED, "solve_failed")
    assert [a["outcome"] for a in ctx.of("solve_attempt")] == ["rejected"] * 3
    assert len(fake.answer_requests) == 3
    assert ctx.one("solve_finished")["reason"] == "solve_failed"


def test_no_gap_ends_the_run_without_any_drag(solve, fake, monkeypatch):
    def finder(background, piece, top):
        raise gap.GapNotFound("test")

    monkeypatch.setitem(gap.FINDERS, "cv", finder)
    result, ctx = solve()

    assert (result.status, result.reason) == (Status.BLOCKED, "gap_not_found")
    assert fake.answer_requests == []
    attempt = ctx.one("solve_attempt")
    assert (attempt["outcome"], attempt["target_x"]) == ("gap_not_found", None)
    assert ctx.one("solve_finished")["reason"] == "gap_not_found"


def test_a_stuck_handle_is_pressed_again_on_the_same_puzzle(solve, fake):
    fake.ignore_presses = 1
    result, ctx = solve()

    assert (result.status, result.reason) == (Status.SUCCESS, "solved")
    attempt = ctx.one("solve_attempt")
    assert attempt["n"] == 1
    assert attempt["stuck_retries"] == 1
    assert attempt["outcome"] == "accepted"
    assert [a["answer"] for a in fake.answer_requests] == [TARGET]
    assert fake.create_requests == 1


def test_a_handle_that_never_moves_gives_up_after_the_retries(solve, fake):
    fake.ignore_presses = 99
    result, ctx = solve(timeouts=replace(SOLVE, solve_attempts=1))

    assert (result.status, result.reason) == (Status.BLOCKED, "solve_failed")
    attempt = ctx.one("solve_attempt")
    assert (attempt["stuck_retries"], attempt["outcome"]) == (2, "no_answer")
    assert fake.answer_requests == []


def test_the_solver_bots_are_registered_for_both_modes_with_a_plain_description():
    assert [b.id for b in BOTS][-4:] == BOT_IDS
    for bot in SOLVER_BOTS:
        assert bot.modes == ["headless", "headful"]
        assert bot.profile is ALL_SIGNALS
        assert "automatic solver" in bot.name
        assert "automatic solver" in bot.description
        assert "all-signals-headless" in bot.description
    cv_linear, cv_eased, sil_linear, sil_eased = SOLVER_BOTS
    assert "cv finder" in cv_linear.name and "linear movement" in cv_linear.name
    assert "eased movement" in cv_eased.name
    assert "silhouette finder" in sil_linear.name and "linear movement" in sil_linear.name
    assert "silhouette finder" in sil_eased.name and "eased movement" in sil_eased.name
    assert "silhouette" in sil_linear.description


@pytest.mark.parametrize("bot", SOLVER_BOTS, ids=BOT_IDS)
def test_each_mode_gets_its_own_browser_profile(bot):
    assert bot.profile_for("headful") is ALL_SIGNALS
    assert bot.profile_for("headless") is ALL_SIGNALS_HEADLESS
    assert bot.profile_for("anything else") is ALL_SIGNALS  # falls back to `profile`


def test_a_profile_passed_in_wins_over_the_mode():
    assert (
        ArcaptchaBot(SOLVER_BOTS[0].spec, profile=ALL_SIGNALS).profile_for("headless")
        is ALL_SIGNALS
    )


def test_a_headless_run_uses_the_headless_profile_and_still_solves(solve):
    result, ctx = solve("arcaptcha-solver-silhouette-eased")  # the fake's context mode is headless

    assert (result.status, result.reason) == (Status.SUCCESS, "solved")
    assert ctx.one("browser_profile")["name"] == "all-signals-headless"
    assert ctx.one("solve_attempt")["outcome"] == "accepted"
