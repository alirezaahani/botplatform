# Copied from the captcha-solve project (src/captcha_solve/detect.py), so this repository builds
# and runs the solver without a dependency on another repository. Only import order and
# formatting were changed here.
"""Locate the missing puzzle piece inside an image.

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
"""

from __future__ import annotations

import cv2
import numpy as np

__all__ = ["find_enclosed_regions", "find_piece_mask"]

# Pixels have to stand out from the local background by this much to count
# as part of the bright fence.
BRIGHTNESS_DELTA = 22

# The fence is only a handful of pixels thick; closing it by 3x3 heals any
# hairline gaps without welding unrelated bright structures together.
FENCE_CLOSE_KERNEL = 3

# Anything smaller than this is background speckle rather than a puzzle piece.
MIN_PIECE_AREA = 150


def _local_background(gray: np.ndarray, kernel: int | None) -> np.ndarray:
    """Slow-but-steady background estimate.

    A median filter large enough to swallow the whole piece (the piece is
    ~40px across) keeps the artwork's gradients while ignoring the cut-out.
    """
    if kernel is None:
        # ~1/4 of the shorter side, forced odd, and always bigger than the
        # piece we are trying to isolate.
        kernel = max(15, min(gray.shape[:2]) // 4)
        kernel += 1 - (kernel % 2)
    kernel = max(3, kernel | 1)
    return cv2.medianBlur(gray, kernel)


def find_enclosed_regions(
    img: np.ndarray,
    *,
    brightness_delta: int = BRIGHTNESS_DELTA,
    bg_kernel: int | None = None,
    close: int = FENCE_CLOSE_KERNEL,
) -> list[tuple[np.ndarray, int]]:
    """Regions fenced off from the image border by a bright ridge.

    Returns ``(mask, area)`` pairs ordered from largest to smallest.
    """
    if img.ndim == 2:
        gray = img
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    background = _local_background(gray, bg_kernel)
    # cv2.subtract saturates at 0, so this is max(gray - background, 0).
    bright = cv2.subtract(gray, background)
    fence = (bright > brightness_delta).astype(np.uint8)

    if close:
        k = np.ones((close, close), np.uint8)
        fence = cv2.morphologyEx(fence, cv2.MORPH_CLOSE, k)

    # Paint every pixel reachable from the image border without crossing the
    # fence with a marker; anything the marker never touched is enclosed.
    free = 1 - fence
    flooded = free.copy()
    fill_mask = np.zeros((gray.shape[0] + 2, gray.shape[1] + 2), np.uint8)
    h, w = gray.shape[:2]
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if flooded[seed[1], seed[0]]:
            cv2.floodFill(flooded, fill_mask, seed, 2)

    enclosed = ((flooded != 2) & (fence == 0)).astype(np.uint8)
    # Drop single-pixel noise that the fence happened to ring in.
    enclosed = cv2.morphologyEx(enclosed, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(enclosed, 8)
    regions = []
    for i in range(1, count):
        regions.append((labels == i, int(stats[i, cv2.CC_STAT_AREA])))
    regions.sort(key=lambda r: r[1], reverse=True)
    return regions


def _strip_thin_appendages(mask: np.ndarray, kernel_size: int = 5) -> np.ndarray:
    """Drop blobs that hang off the piece through a narrow neck.

    A bright fence can be closed by artwork that has nothing to do with the
    piece -- in one sample the white logo and the piece's halo ringed a
    sliver of background and welded a stray blob onto the mask.  Opening
    with a small disc severs such necks (they are only a couple of pixels
    wide) while leaving the ~30px piece body and its knobs untouched; the
    original resolution is then restored by dilating the surviving core
    back out and intersecting it with the mask.
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(opened, 8)
    if count <= 1:
        return mask
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    core = (labels == best).astype(np.uint8)
    return (mask & cv2.dilate(core, kernel)).astype(np.uint8)


def find_piece_mask(
    img: np.ndarray,
    *,
    brightness_delta: int = BRIGHTNESS_DELTA,
    bg_kernel: int | None = None,
    min_area: int = MIN_PIECE_AREA,
) -> np.ndarray | None:
    """Binary mask (uint8, 0/1) of the missing puzzle piece, or None."""
    for mask, area in find_enclosed_regions(
        img, brightness_delta=brightness_delta, bg_kernel=bg_kernel
    ):
        if area >= min_area:
            return _strip_thin_appendages(mask.astype(np.uint8))
    return None
