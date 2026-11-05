"""The halo gap finder against eight real captured puzzles."""

import json
from pathlib import Path

import pytest

from botplatform.bots.arcaptcha import gap_finders as gap
from botplatform.bots.arcaptcha.gap_finders import FINDERS, GapNotFound, find_gap_x_halo

DIR = Path(__file__).parent / "fixtures" / "solver"
MANIFEST = json.loads((DIR / "manifest.json").read_text())
IDS = [row["name"] for row in MANIFEST]


def load(row: dict) -> tuple[bytes, bytes]:
    return (DIR / row["background"]).read_bytes(), (DIR / row["piece"]).read_bytes()


def test_the_manifest_has_the_eight_puzzles():
    assert len(MANIFEST) == 8
    assert set(FINDERS) == {"halo", "silhouette"}
    assert FINDERS["halo"] is find_gap_x_halo


@pytest.mark.parametrize("row", MANIFEST, ids=IDS)
def test_cv_returns_the_expected_target_and_is_near_the_human_answer(row):
    background, piece = load(row)
    target = find_gap_x_halo(background, piece, row["piece_top"])
    assert target == row["halo_target"]
    assert abs(target - row["human_answer"]) <= 5


def test_the_piece_arguments_are_ignored():
    row = MANIFEST[0]
    background, _ = load(row)
    assert find_gap_x_halo(background, b"", 0) == row["halo_target"]


def test_a_blank_image_has_no_gap():
    import cv2
    import numpy as np

    ok, png = cv2.imencode(".png", np.full((160, 260, 3), 120, np.uint8))
    assert ok
    with pytest.raises(GapNotFound):
        find_gap_x_halo(png.tobytes(), b"", 0)


@pytest.mark.parametrize("data", [b"", b"not an image at all", b"\x89PNG\r\n\x1a\ngarbage"])
def test_garbage_bytes_have_no_gap(data):
    with pytest.raises(GapNotFound):
        find_gap_x_halo(data, b"", 0)


@pytest.mark.parametrize("target", [-1, 197, 400])
def test_a_target_outside_the_handle_travel_is_not_found(target):
    with pytest.raises(GapNotFound):
        gap.check_range(target)


@pytest.mark.parametrize("target", [0, 196])
def test_the_ends_of_the_travel_are_valid(target):
    assert gap.check_range(target) == target
