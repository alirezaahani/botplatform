"""The gap by one-dimensional silhouette matching, independent of the halo detector in `detect.py`.

The piece's row (`piece_top`) and exact shape (its alpha channel) are known, so only x is unknown.
For each x the score is the mean brightness in a thin ring just outside the silhouette (the light
halo around the gap) minus the mean brightness inside it (the darkened gap). The answer is the x
with the highest score. No reference data and no use of `find_piece_mask`.
"""

from botplatform.solver.gap import MAX_ANSWER, GapNotFound, check_range

ALPHA_SOLID = 128  # alpha above this counts as part of the silhouette
RING_WIDTH = 5  # elliptical kernel size: the ring is about 2 px wide
# Fixtures: best 119..161, lead over a rival 82..106. Noise, blank and smooth images: best <= 7.2.
MIN_SCORE = 40.0  # the best ring-minus-inside contrast, in gray levels (0..255)
MIN_MARGIN = 20.0  # how far the best must beat every x at least NEAR_PEAK px away
NEAR_PEAK = 8  # positions this close to the best are the same peak, not a rival


def find_gap_x_silhouette(background_png: bytes, piece_png: bytes, piece_top: int) -> int:
    """The x where the piece's silhouette best fits the halo and dark interior of the gap."""
    # Imported here so that importing the bot registry does not need OpenCV.
    import cv2
    import numpy as np

    try:
        image = cv2.imdecode(np.frombuffer(background_png, np.uint8), cv2.IMREAD_GRAYSCALE)
        piece = cv2.imdecode(np.frombuffer(piece_png, np.uint8), cv2.IMREAD_UNCHANGED)
    except cv2.error as error:
        raise GapNotFound(f"cannot decode the images: {error}") from None
    if image is None or piece is None:
        raise GapNotFound("cannot decode the images")
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

    def mean_under(mask):
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
