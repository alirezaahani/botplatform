"""Puzzle capture: each puzzle's images are saved for later study, and a failure is harmless."""

from dataclasses import replace

from botplatform.contract import Status
from tests.bots.arcaptcha.conftest import FAST
from tests.bots.arcaptcha.fake_demo.server import (
    BACKGROUND_PNG,
    CHALLENGE_ID,
    PIECE_PNG,
    create_reply,
)


def test_a_puzzle_is_saved_as_two_images_and_an_event(fake, run_bot):
    fake.creates = [create_reply("puzzle")]
    outcome = run_bot()

    artifacts = {name: (kind, data) for name, kind, data in outcome.ctx.artifacts}
    assert artifacts["puzzle-1-background.png"] == ("image/png", BACKGROUND_PNG)
    assert artifacts["puzzle-1-piece.png"] == ("image/png", PIECE_PNG)
    event = outcome.ctx.one("puzzle_captured")
    assert (event["challenge_id"], event["n"]) == (CHALLENGE_ID, 1)
    assert event["artifacts"] == {
        "background": "puzzle-1-background.png",
        "piece": "puzzle-1-piece.png",
    }
    # The size the browser decoded each image to, and where it put them on the page.
    assert (event["background"]["natural_width"], event["background"]["natural_height"]) == (8, 4)
    assert (event["piece"]["natural_width"], event["piece"]["natural_height"]) == (3, 3)
    assert event["piece"]["style_top"] == "20px"
    assert event["background"]["rect"]["width"] > 0


def test_images_that_cannot_be_fetched_are_noted_and_do_not_change_the_result(fake, run_bot):
    fake.creates = [create_reply("puzzle")]
    fake.break_puzzle_images()
    outcome = run_bot(timeouts=replace(FAST, puzzle_images=1))

    assert outcome.verdict == (Status.BLOCKED, "challenge_unsolved")  # the same as with images
    assert outcome.ctx.one("puzzle_capture_failed")["challenge_id"] == CHALLENGE_ID
    assert outcome.ctx.of("puzzle_captured") == []


def test_images_without_a_content_type_are_saved_as_unknown_bytes(fake, run_bot):
    fake.creates = [create_reply("puzzle")]
    fake.image_type = None
    outcome = run_bot()

    artifacts = {name: (kind, data) for name, kind, data in outcome.ctx.artifacts}
    assert artifacts["puzzle-1-background.bin"] == ("application/octet-stream", BACKGROUND_PNG)
    assert artifacts["puzzle-1-piece.bin"] == ("application/octet-stream", PIECE_PNG)
