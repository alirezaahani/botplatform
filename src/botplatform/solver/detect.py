# Derived from the captcha-solve project (detect.py, geometry.py) and trimmed to the gap's left edge.
"""Locate the missing puzzle piece inside an image, and find the left edge of its body.

The images we deal with are ordinary photographs/graphics with a puzzle
piece cut out of them.  The cut-out is never signalled through the alpha
channel (alpha is fully opaque), so it has to be recovered from RGB.

Every sample we have shares two traits that make it tractable:

1. the piece sits on top of the surrounding artwork, and
2. a light *halo* (a drop-shadow style highlight) is stroked around it.

So the piece is a region of the image that is fenced off from the border by
a bright ridge.  We estimate a smooth background, threshold the pixels that
stand out from it, and flood-fill the free space from the image border.
Whatever the flood cannot reach and is not itself part of the bright ridge
is the missing piece.  This works regardless of whether the piece is black,
navy, brown or a translucent silhouette, because we never look at the piece
colour -- only at the fence around it.

A jigsaw piece is a square *body* with circular knobs poking out of some of its sides, so the
mask's bounding box is stretched by every knob.  The body's edges come from the median of the
mask's row/column extent profiles instead (see `_body_edges`).
"""

import cv2
import numpy as np

# Pixels have to stand out from the local background by this much to count
# as part of the bright fence.
BRIGHTNESS_DELTA = 22

# The fence is only a handful of pixels thick; closing it by 3x3 heals any
# hairline gaps without welding unrelated bright structures together.
FENCE_CLOSE_KERNEL = 3

# Anything smaller than this is background speckle rather than a puzzle piece.
MIN_PIECE_AREA = 150

# `_body_edges` alternates its medians this many times at most; the box settles in two or three.
BODY_EDGE_ROUNDS = 6

# Opening with a disc this size severs the necks of stray blobs (see `_strip_thin_appendages`).
APPENDAGE_KERNEL = 5


def _local_background(gray: np.ndarray) -> np.ndarray:
    """Slow-but-steady background estimate.

    A median filter large enough to swallow the whole piece (the piece is
    ~40px across) keeps the artwork's gradients while ignoring the cut-out.
    """
    # ~1/4 of the shorter side, forced odd, and always bigger than the
    # piece we are trying to isolate.
    kernel = max(15, min(gray.shape[:2]) // 4)
    kernel += 1 - (kernel % 2)
    return cv2.medianBlur(gray, kernel)


def find_enclosed_regions(img: np.ndarray) -> list[tuple[np.ndarray, int]]:
    """Regions fenced off from the image border by a bright ridge.

    Returns ``(mask, area)`` pairs ordered from largest to smallest.
    """
    if img.ndim == 2:
        gray = img
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    background = _local_background(gray)
    # cv2.subtract saturates at 0, so this is max(gray - background, 0).
    bright = cv2.subtract(gray, background)
    fence = (bright > BRIGHTNESS_DELTA).astype(np.uint8)
    fence = cv2.morphologyEx(fence, cv2.MORPH_CLOSE, np.ones((FENCE_CLOSE_KERNEL,) * 2, np.uint8))

    # Paint every pixel reachable from the image border without crossing the
    # fence with a marker; anything the marker never touched is enclosed.
    flooded = 1 - fence
    fill_mask = np.zeros((gray.shape[0] + 2, gray.shape[1] + 2), np.uint8)
    h, w = gray.shape[:2]
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if flooded[seed[1], seed[0]]:
            cv2.floodFill(flooded, fill_mask, seed, 2)

    enclosed = ((flooded != 2) & (fence == 0)).astype(np.uint8)
    # Drop single-pixel noise that the fence happened to ring in.
    enclosed = cv2.morphologyEx(enclosed, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(enclosed, 8)
    regions = [(labels == i, int(stats[i, cv2.CC_STAT_AREA])) for i in range(1, count)]
    regions.sort(key=lambda r: r[1], reverse=True)
    return regions


def _strip_thin_appendages(mask: np.ndarray) -> np.ndarray:
    """Drop blobs that hang off the piece through a narrow neck.

    A bright fence can be closed by artwork that has nothing to do with the
    piece -- in one sample the white logo and the piece's halo ringed a
    sliver of background and welded a stray blob onto the mask.  Opening
    with a small disc severs such necks (they are only a couple of pixels
    wide) while leaving the ~30px piece body and its knobs untouched; the
    original resolution is then restored by dilating the surviving core
    back out and intersecting it with the mask.
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (APPENDAGE_KERNEL,) * 2)
    opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(opened, 8)
    if count <= 1:
        return mask
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    core = (labels == best).astype(np.uint8)
    return (mask & cv2.dilate(core, kernel)).astype(np.uint8)


def find_piece_mask(img: np.ndarray) -> np.ndarray | None:
    """Binary mask (uint8, 0/1) of the missing puzzle piece, or None."""
    for mask, area in find_enclosed_regions(img):
        if area >= MIN_PIECE_AREA:
            return _strip_thin_appendages(mask.astype(np.uint8))
    return None


def body_left(mask: np.ndarray) -> int:
    """The x of the left edge of the piece's body square, knobs ignored."""
    mask = (mask > 0).astype(np.uint8)
    ys, xs = np.where(mask)
    if not len(ys):
        raise ValueError("empty mask")
    box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    return _body_edges(mask, box)[0]


def _body_edges(
    mask: np.ndarray,
    box: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Knob-free body edges as ``(left, top, right, bottom)``.

    A single pass is not enough.  The extent profiles have to be medianed
    over the body's own span, but that span is what we are solving for: on
    a piece carrying knobs on both sides plus a socket, the knob columns
    can outnumber the body columns and drag the median off the body edge
    entirely.  So we start from the full bounding box and alternate --
    median the horizontal edges over the current body rows, the vertical
    edges over the current body columns -- until the box stops moving.
    Nothing is ever cropped away, only the span each median sees shrinks.
    """
    x0, y0, x1, y1 = box
    left, top, right, bottom = x0, y0, x1, y1

    def median_in(values: np.ndarray, lo: int, hi: int) -> int:
        """Median of ``values[lo:hi]``, falling back to everything."""
        segment = values[lo:hi]
        if segment.size == 0:
            segment = values
        return int(np.median(segment))

    for _ in range(BODY_EDGE_ROUNDS):
        top_p, bot_p, left_p, right_p = _extent_profiles(mask, (x0, y0, x1, y1))

        # Profiles are indexed from the box origin: top/bottom by column,
        # left/right by row.
        col_lo, col_hi = left - x0, right - x0 + 1
        row_lo, row_hi = top - y0, bottom - y0 + 1

        new_top = median_in(top_p, col_lo, col_hi)
        new_bottom = median_in(bot_p, col_lo, col_hi)
        new_left = median_in(left_p, row_lo, row_hi)
        new_right = median_in(right_p, row_lo, row_hi)

        if (new_left, new_top, new_right, new_bottom) == (left, top, right, bottom):
            break
        left, top, right, bottom = new_left, new_top, new_right, new_bottom

    return left, top, right, bottom


def _extent_profiles(
    mask: np.ndarray, box: tuple[int, int, int, int]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Per-column top/bottom and per-row left/right extents of the mask."""
    x0, y0, x1, y1 = box
    sub = mask[y0 : y1 + 1, x0 : x1 + 1]

    cols = sub.any(axis=0)
    rows = sub.any(axis=1)

    def _fill(values: np.ndarray, ok: np.ndarray, fallback: float) -> np.ndarray:
        if not ok.any():
            return np.full_like(values, fallback)
        return np.where(ok, values, np.median(values[ok]))

    top = _fill(np.argmax(sub, axis=0) + y0, cols, y0).astype(int)
    bot = _fill(y1 - np.argmax(sub[::-1], axis=0), cols, y1).astype(int)
    left = _fill(np.argmax(sub, axis=1) + x0, rows, x0).astype(int)
    right = _fill(x1 - np.argmax(sub[:, ::-1], axis=1), rows, x1).astype(int)
    return top, bot, left, right
