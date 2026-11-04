"""Puzzle capture: the images and geometry of each puzzle are saved, and a failure is harmless."""

from dataclasses import replace

from botplatform.contract import Status
from tests.conftest import FAST
from tests.fake_demo.server import BACKGROUND_PNG, CHALLENGE_ID, PIECE_PNG, Reply, create_reply
from tests.test_assisted import assisted, person  # noqa: F401 - pytest fixtures

SECOND_ID = "999999999999999999999999999999"
ACCEPTED = Reply(json={"status": "OK", "accepted": True})
REJECTED = Reply(json={"status": "OK", "accepted": False})


def test_a_puzzle_is_captured_as_two_artifacts_and_an_event(fake, run_bot):
    fake.creates = [create_reply("puzzle")]
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (Status.BLOCKED, "challenge_unsolved")
    artifacts = {name: (kind, data) for name, kind, data in outcome.ctx.artifacts}
    assert artifacts["puzzle-1-background.png"] == ("image/png", BACKGROUND_PNG)
    assert artifacts["puzzle-1-piece.png"] == ("image/png", PIECE_PNG)
    event = outcome.ctx.one("puzzle_captured")
    assert (event["challenge_id"], event["n"]) == (CHALLENGE_ID, 1)
    assert event["artifacts"] == {
        "background": "puzzle-1-background.png",
        "piece": "puzzle-1-piece.png",
    }
    background, piece = event["background"], event["piece"]
    assert background["src"].endswith(f"/puzzles/{CHALLENGE_ID}/undefined/background")
    assert piece["src"].endswith(f"/puzzles/{CHALLENGE_ID}/undefined/piece")
    assert (background["natural_width"], background["natural_height"]) == (8, 4)
    assert (piece["natural_width"], piece["natural_height"]) == (3, 3)
    assert (background["rect"]["width"], background["rect"]["height"]) == (260, 160)
    assert piece["rect"]["width"] == 40
    assert (piece["style_left"], piece["style_top"]) == ("0px", "20px")
    assert (piece["computed_left"], piece["computed_top"]) == ("0px", "20px")
    assert (event["wrapper_rect"]["width"], event["wrapper_rect"]["height"]) == (260, 160)
    assert event["piece_parent_rect"] is not None
    assert event["slider_candidates"] == []  # the fake has no slider
    assert event["device_pixel_ratio"] > 0
    assert outcome.ctx.of("puzzle_capture_failed") == []


def test_a_second_puzzle_after_a_rejected_answer_is_number_two(fake, assisted, person):  # noqa: F811
    fake.creates = [create_reply("puzzle"), create_reply("puzzle", challenge_id=SECOND_ID)]
    fake.answers = [REJECTED, ACCEPTED]
    person(2)
    result, ctx = assisted()

    assert (result.status, result.reason) == (Status.SUCCESS, "human_solved")
    events = ctx.of("puzzle_captured")
    assert [(e["n"], e["challenge_id"]) for e in events] == [(1, CHALLENGE_ID), (2, SECOND_ID)]
    names = [name for name, _, _ in ctx.artifacts if name.startswith("puzzle-")]
    assert names == [
        "puzzle-1-background.png",
        "puzzle-1-piece.png",
        "puzzle-2-background.png",
        "puzzle-2-piece.png",
    ]
    # The order of events pairs each puzzle with the answer that followed it.
    kinds = [
        (kind, data.get("n") if kind == "puzzle_captured" else data["request"]["challenge_id"])
        for kind, data in ctx.events
        if kind in ("puzzle_captured", "answer_request")
    ]
    assert kinds == [
        ("puzzle_captured", 1),
        ("answer_request", CHALLENGE_ID),
        ("puzzle_captured", 2),
        ("answer_request", SECOND_ID),
    ]


def test_the_capture_event_comes_before_the_answer_it_belongs_to(fake, run_bot):
    fake.creates = [create_reply("puzzle")]
    outcome = run_bot()
    kinds = [kind for kind, _ in outcome.ctx.events]
    assert kinds.index("puzzle_captured") > kinds.index("create_response")


def test_broken_images_record_a_failure_and_leave_the_result_unchanged(fake, run_bot):
    fake.creates = [create_reply("puzzle")]
    baseline = run_bot()

    fake.broken_puzzle_images = True
    outcome = run_bot(timeouts=replace(FAST, puzzle_images=1))

    assert (outcome.result.status, outcome.result.reason) == (
        baseline.result.status,
        baseline.result.reason,
    )
    failed = outcome.ctx.one("puzzle_capture_failed")
    assert (failed["challenge_id"], failed["n"]) == (CHALLENGE_ID, 1)
    assert outcome.ctx.of("puzzle_captured") == []
    assert not [a for a in outcome.ctx.artifacts if a[0].startswith("puzzle-")]


def test_no_capture_for_other_types(fake, run_bot):
    outcome = run_bot()
    assert outcome.ctx.of("puzzle_captured") == []
    assert outcome.ctx.of("puzzle_capture_failed") == []
