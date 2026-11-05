"""Puzzle capture: the images and geometry of each puzzle are saved, and a failure is harmless."""

from botplatform.contract import Status
from tests.fake_demo.server import BACKGROUND_PNG, CHALLENGE_ID, PIECE_PNG, create_reply


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
