"""The solver bots against the fake demo, which accepts an answer equal to the known target."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from botplatform.bots import BOTS
from botplatform.bots.arcaptcha import SOLVER_BOTS
from botplatform.contract import Status
from botplatform.bots.utils.profiles import ALL_SIGNALS, ALL_SIGNALS_HEADLESS
from botplatform.solver import gap
from tests.conftest import FAST
from tests.fake_demo.server import Puzzle

DIR = Path(__file__).parent / "fixtures" / "solver"
ROW = json.loads((DIR / "manifest.json").read_text())[0]
TARGET = ROW["halo_target"]
PUZZLE = Puzzle((DIR / ROW["background"]).read_bytes(), (DIR / ROW["piece"]).read_bytes(), top=60)
IDS = [f"{i:030d}" for i in range(1, 6)]
SOLVE = replace(FAST, puzzle_ready=6, puzzle_images=4, answer_settle=1.5, solve_attempts=3)


@pytest.fixture
def fake_puzzles(fake):
    """The fake serves the fixture puzzle again and again, and accepts only the right answer."""
    fake.serve_puzzles(PUZZLE, target=TARGET, ids=IDS)
    return fake


def finder_returning(monkeypatch, *targets):
    """Make the `halo` finder answer with these targets in turn (the last one repeats)."""
    values = list(targets)
    monkeypatch.setitem(
        gap.FINDERS,
        "halo",
        lambda background, piece, top: values.pop(0) if len(values) > 1 else values[0],
    )


# One run for each finder and each movement is enough: the bots differ only in these two names.
@pytest.mark.parametrize(
    "bot_id", ["arcaptcha-solver-halo-linear", "arcaptcha-solver-silhouette-eased"]
)
def test_the_solver_drags_the_piece_to_the_gap_and_the_login_judges_the_run(
    fake_puzzles, run_bot, bot_id
):
    outcome = run_bot(bot_id, timeouts=SOLVE)

    assert outcome.verdict == (Status.SUCCESS, "solved")
    assert fake_puzzles.answers == [TARGET]
    assert len(fake_puzzles.logins) == 1
    attempt = outcome.ctx.one("solve_attempt")
    assert attempt["outcome"] == "accepted"
    assert attempt["challenge_id"] == IDS[0]
    assert (attempt["handle_left"], attempt["piece_left"]) == (TARGET, TARGET)


def test_a_wrong_answer_brings_a_new_puzzle_and_the_next_attempt_can_succeed(
    fake_puzzles, run_bot, monkeypatch
):
    finder_returning(monkeypatch, 50, TARGET)
    outcome = run_bot("arcaptcha-solver-halo-linear", timeouts=SOLVE)

    assert outcome.verdict == (Status.SUCCESS, "solved")
    assert fake_puzzles.answers == [50, TARGET]
    attempts = outcome.ctx.of("solve_attempt")
    assert [a["outcome"] for a in attempts] == ["rejected", "accepted"]
    assert [a["challenge_id"] for a in attempts] == IDS[:2]  # each attempt is on its own puzzle


def test_the_solver_gives_up_after_its_attempts_are_all_rejected(
    fake_puzzles, run_bot, monkeypatch
):
    finder_returning(monkeypatch, 50)
    outcome = run_bot("arcaptcha-solver-halo-linear", timeouts=replace(SOLVE, solve_attempts=2))

    assert outcome.verdict == (Status.BLOCKED, "solve_failed")
    assert fake_puzzles.answers == [50, 50]


def test_when_no_gap_is_found_nothing_is_dragged(fake_puzzles, run_bot, monkeypatch):
    def finder(background, piece, top):
        raise gap.GapNotFound("test")

    monkeypatch.setitem(gap.FINDERS, "halo", finder)
    outcome = run_bot("arcaptcha-solver-halo-linear", timeouts=SOLVE)

    assert outcome.verdict == (Status.BLOCKED, "gap_not_found")
    assert fake_puzzles.answers == []


def test_a_handle_that_ignored_the_press_is_pressed_again_on_the_same_puzzle(fake_puzzles, run_bot):
    fake_puzzles.serve_puzzles(PUZZLE, target=TARGET, ids=IDS, ignore_presses=1)
    outcome = run_bot("arcaptcha-solver-halo-linear", timeouts=SOLVE)

    assert outcome.verdict == (Status.SUCCESS, "solved")
    assert fake_puzzles.answers == [TARGET]
    assert fake_puzzles.create_requests == 1  # no new puzzle was needed for the second press
    assert outcome.ctx.one("solve_attempt")["stuck_retries"] == 1


def test_a_handle_that_never_responds_ends_the_run_without_an_answer(fake_puzzles, run_bot):
    fake_puzzles.serve_puzzles(PUZZLE, target=TARGET, ids=IDS, ignore_presses=99)
    outcome = run_bot(
        "arcaptcha-solver-halo-linear", timeouts=replace(SOLVE, solve_attempts=1, stuck_retries=1)
    )

    assert outcome.verdict == (Status.BLOCKED, "solve_failed")
    assert fake_puzzles.answers == []


@pytest.mark.parametrize("bot", SOLVER_BOTS, ids=[bot.id for bot in SOLVER_BOTS])
def test_each_solver_bot_is_registered_and_picks_its_profile_by_mode(bot):
    assert bot in BOTS
    assert bot.modes == ["headless", "headful"]
    assert bot.profile_for("headful") is ALL_SIGNALS
    assert bot.profile_for("headless") is ALL_SIGNALS_HEADLESS
