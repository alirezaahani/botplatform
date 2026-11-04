"""The silhouette gap finder against eight real captured puzzles, and against bad input."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from botplatform.solver.gap import FINDERS, GapNotFound
from botplatform.solver.silhouette import find_gap_x_silhouette

DIR = Path(__file__).parent / "fixtures" / "solver"
MANIFEST = json.loads((DIR / "manifest.json").read_text())
IDS = [row["name"] for row in MANIFEST]
PIECE = (DIR / MANIFEST[0]["piece"]).read_bytes()


def load(row: dict) -> tuple[bytes, bytes]:
    return (DIR / row["background"]).read_bytes(), (DIR / row["piece"]).read_bytes()


def png(array) -> bytes:
    ok, data = cv2.imencode(".png", array)
    assert ok
    return data.tobytes()


def test_it_is_registered_by_name():
    assert FINDERS["silhouette"](*load(MANIFEST[0]), MANIFEST[0]["piece_top"]) == 60


@pytest.mark.parametrize("row", MANIFEST, ids=IDS)
def test_it_matches_the_cv_target_exactly_on_every_fixture(row):
    background, piece = load(row)
    found = find_gap_x_silhouette(background, piece, row["piece_top"])
    assert found == row["cv_target"]
    assert abs(found - row["human_answer"]) <= 5


def test_a_blank_background_has_no_gap():
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(png(np.full((160, 260, 3), 120, np.uint8)), PIECE, 60)


def test_a_noise_background_has_no_gap():
    noise = np.random.default_rng(1).integers(0, 256, (160, 260, 3), dtype=np.uint8)
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(png(noise), PIECE, 60)


@pytest.mark.parametrize("data", [b"", b"not an image at all", b"\x89PNG\r\n\x1a\ngarbage"])
def test_garbage_bytes_have_no_gap(data):
    background, piece = load(MANIFEST[0])
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(data, piece, 60)
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(background, data, 60)


@pytest.mark.parametrize("alpha", [0, 255])
def test_a_piece_without_a_silhouette_has_no_gap(alpha):
    piece = np.zeros((50, 50, 4), np.uint8)
    piece[:, :, 3] = alpha
    background, _ = load(MANIFEST[0])
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(background, png(piece), 60)


def test_a_piece_without_an_alpha_channel_has_no_gap():
    background, _ = load(MANIFEST[0])
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(background, png(np.zeros((50, 50, 3), np.uint8)), 60)


def test_a_row_outside_the_background_has_no_gap():
    background, piece = load(MANIFEST[0])
    with pytest.raises(GapNotFound):
        find_gap_x_silhouette(background, piece, 150)
