"""Finding the gap: the answer (in px) for a slider puzzle.

A finder has the signature `find_gap_x(background_png, piece_png, piece_top) -> int` and returns
the value to send as the answer, which is also the handle's final `left`. It raises `GapNotFound`
when it finds nothing or the result is outside the handle's travel. Finders are registered by name
in `FINDERS`, so a different method can be compared with the same bot code.
"""

from collections.abc import Callable

# The handle is 64 px wide on a 260 px track, so the valid answers are 0..196 (seen live).
MIN_ANSWER = 0
MAX_ANSWER = 196
# Live data: the right answer is the gap's body square left edge minus this offset.
BODY_TO_ANSWER_OFFSET = 10

GapFinder = Callable[[bytes, bytes, int], int]


class GapNotFound(Exception):
    """The finder found no gap, or its target cannot be reached by the handle."""


def check_range(target: int) -> int:
    if not MIN_ANSWER <= target <= MAX_ANSWER:
        raise GapNotFound(f"target {target} is outside {MIN_ANSWER}..{MAX_ANSWER}")
    return target


def find_gap_x_cv(background_png: bytes, piece_png: bytes, piece_top: int) -> int:
    """The gap by image analysis of the background alone (the piece arguments are ignored).

    Uses the vendored detection from the captcha-solve project on the background decoded in
    memory: the gap body square's left x, minus 10.
    """
    # Imported here so that importing the bot registry does not need OpenCV.
    import cv2
    import numpy as np

    from botplatform.solver.cv.detect import find_piece_mask
    from botplatform.solver.cv.geometry import extract_geometry

    try:
        image = cv2.imdecode(np.frombuffer(background_png, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as error:
        raise GapNotFound(f"cannot decode the background: {error}") from None
    if image is None:
        raise GapNotFound("cannot decode the background")
    try:
        mask = find_piece_mask(image)
        if mask is None:
            raise GapNotFound("no gap found in the background")
        geometry = extract_geometry(mask)
    except (ValueError, cv2.error) as error:
        raise GapNotFound(f"gap analysis failed: {error}") from None
    return check_range(int(geometry.body_bbox[0]) - BODY_TO_ANSWER_OFFSET)


FINDERS: dict[str, GapFinder] = {"cv": find_gap_x_cv}
