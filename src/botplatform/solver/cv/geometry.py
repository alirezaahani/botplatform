# Copied from the captcha-solve project (src/captcha_solve/geometry.py), so this repository builds
# and runs the solver without a dependency on another repository. Only import order and
# formatting were changed here.
"""Turn a missing-piece mask into usable geometry.

A jigsaw piece is a square *body* with circular knobs poking out of some of
its four sides.  So the useful coordinates are not just the raw bounding
box (which is stretched by every knob) but:

* the body square -- its corners and its four edges,
* per side, whether a knob is present, how far it protrudes, how wide it
  is and where its centre sits, and
* the centroid of the whole shape.

The body edges come from the median of the mask's row/column extent
profiles: wherever a knob sticks out the profile jumps outward over the
knob, everywhere else it rests on the body edge, and a median ignores the
knob as long as it covers less than half the side.  Once the body square is
known, each knob is simply the run of mask pixels lying outside it on that
side.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

__all__ = ["Edge", "PieceGeometry", "Tab", "extract_geometry"]

SIDES = ("top", "right", "bottom", "left")

# Knobs on our samples protrude ~8px from a ~30px body while mask noise is
# only 1-2px, so anything short of 4px is not a knob.
TAB_MIN_DEPTH = 4


@dataclass
class Tab:
    """A knob protruding from one side of the piece."""

    side: str
    present: bool
    depth: int  # how far it sticks out of the body, in px
    start: float  # first coordinate along the side
    end: float  # last coordinate along the side
    center: tuple[float, float]  # centroid of the knob
    tip: tuple[float, float]  # furthest point of the knob

    @property
    def width(self) -> float:
        return self.end - self.start


@dataclass
class Edge:
    """One side of the body square, as a line segment."""

    side: str
    p0: tuple[float, float]
    p1: tuple[float, float]
    tab: Tab

    @property
    def has_tab(self) -> bool:
        return self.tab.present


@dataclass
class PieceGeometry:
    mask: np.ndarray
    contour: np.ndarray  # (N, 1, 2) int32, full-resolution boundary
    bbox: tuple[int, int, int, int]  # x, y, w, h -- knobs included
    body_bbox: tuple[int, int, int, int]  # x, y, w, h -- knob-free square
    area: int
    center: tuple[float, float]  # centroid of the whole shape
    body_center: tuple[float, float]  # centre of the body square
    corners: dict[str, tuple[float, float]]
    edges: dict[str, Edge]

    # -- convenience ----------------------------------------------------
    @property
    def has_tabs(self) -> dict[str, bool]:
        return {side: self.edges[side].has_tab for side in SIDES}

    def polygon(self, epsilon: float = 1.5) -> np.ndarray:
        """Simplified boundary polygon (approxPolyDP)."""
        return cv2.approxPolyDP(self.contour, epsilon, False)

    def to_dict(self) -> dict:
        """JSON-serialisable view of the geometry."""
        return {
            "bbox": list(self.bbox),
            "body_bbox": list(self.body_bbox),
            "area": self.area,
            "center": [round(v, 2) for v in self.center],
            "body_center": [round(v, 2) for v in self.body_center],
            "corners": {k: list(v) for k, v in self.corners.items()},
            "edges": {
                side: {
                    "p0": list(edge.p0),
                    "p1": list(edge.p1),
                    "has_tab": edge.has_tab,
                    "tab": {
                        "depth": edge.tab.depth,
                        "width": round(edge.tab.width, 1),
                        "start": round(edge.tab.start, 1),
                        "end": round(edge.tab.end, 1),
                        "center": [round(v, 2) for v in edge.tab.center],
                        "tip": [round(v, 2) for v in edge.tab.tip],
                    },
                }
                for side, edge in self.edges.items()
            },
            "tabs": [s for s in SIDES if self.edges[s].has_tab],
            "boundary": [[int(x), int(y)] for x, y in self.contour.reshape(-1, 2)],
        }


def _body_edges(
    mask: np.ndarray,
    box: tuple[int, int, int, int],
    rounds: int = 6,
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

    for _ in range(rounds):
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


def _largest_component(region: np.ndarray) -> np.ndarray:
    """Keep only the biggest blob of a (possibly speckled) region."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(region, 8)
    if count <= 1:
        return region
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (labels == best).astype(np.uint8)


def _measure_tab(
    side: str,
    knob: np.ndarray,
    origin: tuple[int, int],
    depth: int,
    present: bool,
) -> Tab:
    """Describe a knob given its pixels and where the body edge sits."""
    if not present or knob.sum() == 0:
        return Tab(side, False, 0, 0.0, 0.0, (0.0, 0.0), (0.0, 0.0))

    ox, oy = origin
    ys, xs = np.where(knob)
    ys = ys + oy
    xs = xs + ox

    moments = cv2.moments(knob, binaryImage=True)
    if moments["m00"]:
        center = (
            float(moments["m10"] / moments["m00"]) + ox,
            float(moments["m01"] / moments["m00"]) + oy,
        )
    else:
        center = (float(xs.mean()), float(ys.mean()))

    if side in ("top", "bottom"):
        start, end = float(xs.min()), float(xs.max())
        extreme = int(ys.min()) if side == "top" else int(ys.max())
        tip_along = float(xs[ys == extreme].mean())
        tip = (tip_along, float(extreme))
    else:
        start, end = float(ys.min()), float(ys.max())
        extreme = int(xs.min()) if side == "left" else int(xs.max())
        tip_along = float(ys[xs == extreme].mean())
        tip = (float(extreme), tip_along)

    return Tab(side, True, int(depth), start, end, center, tip)


def extract_geometry(mask: np.ndarray, *, tab_min_depth: int = TAB_MIN_DEPTH) -> PieceGeometry:
    """Derive body square, edges, knobs and centres from a piece mask."""
    mask = (mask > 0).astype(np.uint8)
    ys, xs = np.where(mask)
    if not len(ys):
        raise ValueError("empty mask")

    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bbox = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)

    body_left, body_top, body_right, body_bot = _body_edges(mask, (x0, y0, x1, y1))

    # Each knob is whatever sticks out of the body square on that side.
    regions = {
        "top": (mask[y0:body_top, x0 : x1 + 1], (x0, y0), body_top - y0),
        "bottom": (
            mask[body_bot + 1 : y1 + 1, x0 : x1 + 1],
            (x0, body_bot + 1),
            y1 - body_bot,
        ),
        "left": (mask[y0 : y1 + 1, x0:body_left], (x0, y0), body_left - x0),
        "right": (
            mask[y0 : y1 + 1, body_right + 1 : x1 + 1],
            (body_right + 1, y0),
            x1 - body_right,
        ),
    }

    tabs: dict[str, Tab] = {}
    for side, (region, origin, depth) in regions.items():
        knob = _largest_component(region) if region.size else region
        tabs[side] = _measure_tab(side, knob, origin, depth, depth >= tab_min_depth)

    corners = {
        "top_left": (body_left, body_top),
        "top_right": (body_right, body_top),
        "bottom_right": (body_right, body_bot),
        "bottom_left": (body_left, body_bot),
    }

    edges = {
        "top": Edge("top", corners["top_left"], corners["top_right"], tabs["top"]),
        "right": Edge("right", corners["top_right"], corners["bottom_right"], tabs["right"]),
        "bottom": Edge("bottom", corners["bottom_left"], corners["bottom_right"], tabs["bottom"]),
        "left": Edge("left", corners["top_left"], corners["bottom_left"], tabs["left"]),
    }

    moments = cv2.moments(mask, binaryImage=True)
    if moments["m00"]:
        center = (
            float(moments["m10"] / moments["m00"]),
            float(moments["m01"] / moments["m00"]),
        )
    else:
        center = ((x0 + x1) / 2, (y0 + y1) / 2)

    body_bbox = (
        body_left,
        body_top,
        body_right - body_left + 1,
        body_bot - body_top + 1,
    )

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contour = max(contours, key=cv2.contourArea)

    return PieceGeometry(
        mask=mask,
        contour=contour,
        bbox=bbox,
        body_bbox=body_bbox,
        area=int(mask.sum()),
        center=center,
        body_center=((body_left + body_right) / 2, (body_top + body_bot) / 2),
        corners=corners,
        edges=edges,
    )
