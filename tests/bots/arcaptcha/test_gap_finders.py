"""Both gap finders, halo and silhouette, against eight real captured puzzles and bad input."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from botplatform.bots.arcaptcha import gap_finders as gap
from botplatform.bots.arcaptcha.gap_finders import (
    FINDERS,
    GapNotFound,
    find_gap_x_halo,
    find_gap_x_silhouette,
)

DIR = Path(__file__).parent / "fixtures" / "solver"
MANIFEST = json.loads((DIR / "manifest.json").read_text())
IDS = [row["name"] for row in MANIFEST]


def load(row: dict) -> tuple[bytes, bytes]:
    return (DIR / row["background"]).read_bytes(), (DIR / row["piece"]).read_bytes()


def test_the_manifest_has_the_eight_puzzles():
    assert len(MANIFEST) == 8
    assert set(FINDERS) == {"halo", "silhouette"}
    assert FINDERS["halo"] is find_gap_x_halo


PIECE = (DIR / MANIFEST[0]["piece"]).read_bytes()


def png(array) -> bytes:
    ok, data = cv2.imencode(".png", array)
    assert ok
    return data.tobytes()


@pytest.mark.parametrize("row", MANIFEST, ids=IDS)
def test_halo_returns_the_expected_target_and_is_near_the_human_answer(row):
    background, piece = load(row)
    target = find_gap_x_halo(background, piece, row["piece_top"])
    assert target == row["halo_target"]
    assert abs(target - row["human_answer"]) <= 5


def test_halo_ignores_the_piece_arguments():
    row = MANIFEST[0]
    background, _ = load(row)
    assert find_gap_x_halo(background, b"", 0) == row["halo_target"]


def test_halo_finds_no_gap_in_a_blank_image():
    with pytest.raises(GapNotFound):
        find_gap_x_halo(png(np.full((160, 260, 3), 120, np.uint8)), b"", 0)


@pytest.mark.parametrize("data", [b"", b"not an image at all", b"\x89PNG\r\n\x1a\ngarbage"])
def test_halo_finds_no_gap_in_garbage_bytes(data):
    with pytest.raises(GapNotFound):
        find_gap_x_halo(data, b"", 0)


@pytest.mark.parametrize("target", [-1, 197, 400])
def test_a_target_outside_the_handle_travel_is_not_found(target):
    with pytest.raises(GapNotFound):
        gap.check_range(target)


@pytest.mark.parametrize("target", [0, 196])
def test_the_ends_of_the_travel_are_valid(target):
    assert gap.check_range(target) == target


# -- silhouette ---------------------------------------------------------------------------------


def test_silhouette_is_registered_by_name():
    assert FINDERS["silhouette"](*load(MANIFEST[0]), MANIFEST[0]["piece_top"]) == 60


@pytest.mark.parametrize("row", MANIFEST, ids=IDS)
def test_silhouette_matches_the_halo_target_exactly_on_every_fixture(row):
    background, piece = load(row)
    found = find_gap_x_silhouette(background, piece, row["piece_top"])
    assert found == row["halo_target"]
    assert abs(found - row["human_answer"]) <= 5


def test_silhouette_finds_no_gap_in_a_blank_background():
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(png(np.full((160, 260, 3), 120, np.uint8)), PIECE, 60)


def test_silhouette_finds_no_gap_in_noise():
    noise = np.random.default_rng(1).integers(0, 256, (160, 260, 3), dtype=np.uint8)
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(png(noise), PIECE, 60)


@pytest.mark.parametrize("data", [b"", b"not an image at all", b"\x89PNG\r\n\x1a\ngarbage"])
def test_silhouette_finds_no_gap_in_garbage_bytes(data):
    background, piece = load(MANIFEST[0])
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(data, piece, 60)
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(background, data, 60)


@pytest.mark.parametrize("alpha", [0, 255])
def test_silhouette_needs_a_piece_with_a_silhouette(alpha):
    piece = np.zeros((50, 50, 4), np.uint8)
    piece[:, :, 3] = alpha
    background, _ = load(MANIFEST[0])
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(background, png(piece), 60)


def test_silhouette_needs_a_piece_with_an_alpha_channel():
    background, _ = load(MANIFEST[0])
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(background, png(np.zeros((50, 50, 3), np.uint8)), 60)


def test_silhouette_finds_no_gap_for_a_row_outside_the_background():
    background, piece = load(MANIFEST[0])
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(background, piece, 150)
