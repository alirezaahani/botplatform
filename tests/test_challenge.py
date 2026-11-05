"""The challenge strategies and the solver's attempt record. No Chrome."""

from botplatform.bots.arcaptcha import BASELINE_SPEC, GiveUp, SliderSolver, solver_spec
from botplatform.bots.arcaptcha.solver import Attempt
from botplatform.contract import BotResult, Status

EVENT_KEYS = [
    "n",
    "puzzle",
    "challenge_id",
    "finder",
    "target_x",
    "mover",
    "dx",
    "duration",
    "steps",
    "stuck_retries",
    "outcome",
    "handle_left",
    "piece_left",
]


def test_give_up_ends_the_challenge_as_unsolved():
    assert GiveUp().resolve(None) == BotResult(Status.BLOCKED, "challenge_unsolved")


def test_a_fresh_attempt_shows_the_default_keys_in_order():
    event = Attempt(n=1, puzzle=2, challenge_id="c", finder="cv", mover="linear").as_event()

    assert list(event) == EVENT_KEYS
    assert event["target_x"] is None
    assert event["stuck_retries"] == 0
    assert (event["n"], event["puzzle"], event["finder"], event["mover"]) == (1, 2, "cv", "linear")


def test_message_and_error_appear_only_when_set():
    base = {"n": 1, "puzzle": 1, "challenge_id": None, "finder": "cv", "mover": "linear"}

    assert list(Attempt(**base, message="no gap").as_event()) == [*EVENT_KEYS, "message"]
    assert list(Attempt(**base, error="Boom: x").as_event()) == [*EVENT_KEYS, "error"]


def test_a_spec_gives_up_by_default_and_a_solver_spec_carries_a_slider_solver():
    assert isinstance(BASELINE_SPEC.challenge, GiveUp)
    assert solver_spec("cv", "eased").challenge == SliderSolver("cv", "eased")
