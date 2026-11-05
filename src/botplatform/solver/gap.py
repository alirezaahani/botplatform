"""Finding the gap: the answer (in px) for a slider puzzle.

A finder has the signature `find_gap_x(background_png, piece_png, piece_top) -> int` and returns
the value to send as the answer, which is also the handle's final `left`. It raises `GapNotFound`
when it finds nothing or the result is outside the handle's travel. Finders are registered by name
in `FINDERS`, so a different method can be compared with the same bot code.
"""

from collections.abc import Callable

import cv2
import numpy as np

from botplatform.solver.detect import body_left, find_piece_mask

# The handle is 64 px wide on a 260 px track, so the valid answers are 0..196 (seen live).
MIN_ANSWER = 0
MAX_ANSWER = 196
# Live data: the right answer is the gap's body square left edge minus this offset.
BODY_TO_ANSWER_OFFSET = 10

GapFinder = Callable[[bytes, bytes, int], int]


class GapNotFound(Exception):
    """The finder found no gap, or its target cannot be reached by the handle."""


def _decode(data: bytes, flags: int, what: str) -> np.ndarray:
    """An image from its bytes (`flags` as for `cv2.imdecode`), or GapNotFound."""
    try:
        image = cv2.imdecode(np.frombuffer(data, np.uint8), flags)
    except cv2.error as error:
        raise GapNotFound(f"cannot decode {what}: {error}") from None
    if image is None:
        raise GapNotFound(f"cannot decode {what}")
    return image


def check_range(target: int) -> int:
    if not MIN_ANSWER <= target <= MAX_ANSWER:
        raise GapNotFound(f"target {target} is outside {MIN_ANSWER}..{MAX_ANSWER}")
    return target


def find_gap_x_halo(background_png: bytes, piece_png: bytes, piece_top: int) -> int:
    """The gap by image analysis of the background alone (the piece arguments are ignored).

    Uses the detection in `detect.py` on the background decoded in memory: the gap body
    square's left x, minus 10.
    """
    image = _decode(background_png, cv2.IMREAD_COLOR, "the background")
    try:
        mask = find_piece_mask(image)
        if mask is None:
            raise GapNotFound("no gap found in the background")
        left = body_left(mask)
    except (ValueError, cv2.error) as error:
        raise GapNotFound(f"gap analysis failed: {error}") from None
    return check_range(left - BODY_TO_ANSWER_OFFSET)


ALPHA_SOLID = 128  # alpha above this counts as part of the silhouette
RING_WIDTH = 5  # elliptical kernel size: the ring is about 2 px wide
# Fixtures: best 119..161, lead over a rival 82..106. Noise, blank and smooth images: best <= 7.2.
MIN_SCORE = 40.0  # the best ring-minus-inside contrast, in gray levels (0..255)
MIN_MARGIN = 20.0  # how far the best must beat every x at least NEAR_PEAK px away
NEAR_PEAK = 8  # positions this close to the best are the same peak, not a rival


def find_gap_x_silhouette(background_png: bytes, piece_png: bytes, piece_top: int) -> int:
    """The gap by one-dimensional silhouette matching, independent of the halo detector.

    The piece's row (`piece_top`) and exact shape (its alpha channel) are known, so only x is
    unknown. For each x the score is the mean brightness in a thin ring just outside the
    silhouette (the light halo around the gap) minus the mean brightness inside it (the darkened
    gap). The answer is the x with the highest score. No reference data and no use of
    `find_piece_mask`.
    """
    image = _decode(background_png, cv2.IMREAD_GRAYSCALE, "the images")
    piece = _decode(piece_png, cv2.IMREAD_UNCHANGED, "the images")
    if piece.ndim != 3 or piece.shape[2] != 4:
        raise GapNotFound("the piece has no alpha channel")
    inside = (piece[:, :, 3] > ALPHA_SOLID).astype(np.uint8)
    height, width = inside.shape
    if not inside.any() or inside.all():
        raise GapNotFound("the piece alpha holds no silhouette")
    if piece_top < 0 or piece_top + height > image.shape[0] or width > image.shape[1]:
        raise GapNotFound("the piece row is outside the background")

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (RING_WIDTH, RING_WIDTH))
    ring = cv2.dilate(inside, kernel) - inside
    strip = image[piece_top : piece_top + height].astype(np.float32)

    def mean_under(mask: np.ndarray) -> np.ndarray:
        mask = mask.astype(np.float32)
        return cv2.matchTemplate(strip, mask, cv2.TM_CCORR)[0] / mask.sum()

    scores = (mean_under(ring) - mean_under(inside))[: MAX_ANSWER + 1]
    best = int(np.argmax(scores))
    rivals = np.abs(np.arange(len(scores)) - best) >= NEAR_PEAK
    runner_up = scores[rivals].max() if rivals.any() else -np.inf
    if scores[best] < MIN_SCORE or scores[best] - runner_up < MIN_MARGIN:
        raise GapNotFound(
            f"no clear silhouette match (best {scores[best]:.1f}, rival {runner_up:.1f})"
        )
    return check_range(best)


FINDERS: dict[str, GapFinder] = {"halo": find_gap_x_halo, "silhouette": find_gap_x_silhouette}
