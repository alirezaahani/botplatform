"""Capturing the puzzle's images and geometry."""

from pydantic import BaseModel, ConfigDict

from botplatform.bots.arcaptcha.session import CapturedPuzzle, Session
from botplatform.bots.utils.browser import describe, wait_for
from botplatform.bots.utils.page_scripts import fetch_in_page, save_fetched

# The puzzle's images. The piece is `img.puzzle` and the background is the other image whose src
# has `/puzzles/` (both seen in the real DOM). It also records the rectangles around them. A src
# already in `seen` belongs to an earlier puzzle.
PUZZLE_INFO_JS = """
const seen = arguments[0];
const piece = document.querySelector('img.puzzle');
if (!piece || !piece.src) return null;
const background = Array.from(document.querySelectorAll('img')).find(
  (img) => img !== piece && img.src.includes('/puzzles/')
);
if (!background || !background.src) return null;
if (seen.includes(piece.src) || seen.includes(background.src)) return null;
const loaded = (img) => img.complete && img.naturalWidth > 0;
if (!loaded(piece) || !loaded(background)) return null;
const rect = (el) => {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {x: r.x, y: r.y, width: r.width, height: r.height};
};
const image = (img) => ({
  src: img.src, natural_width: img.naturalWidth, natural_height: img.naturalHeight,
  rect: rect(img)
});
const computed = getComputedStyle(piece);
return {
  background: image(background),
  piece: Object.assign(image(piece), {
    style_left: piece.style.left, style_top: piece.style.top,
    computed_left: computed.left, computed_top: computed.top
  }),
  wrapper_rect: rect(background.parentElement),
  piece_parent_rect: rect(piece.parentElement),
  device_pixel_ratio: window.devicePixelRatio
};
"""


# Only the fields we read are required. The rest of the script's result is kept (`extra="allow"`)
# so the `puzzle_captured` event still records it.
class Image(BaseModel):
    model_config = ConfigDict(extra="allow")

    src: str


class Piece(Image):
    style_top: str


class PuzzleInfo(BaseModel):
    """What `PUZZLE_INFO_JS` returns once a puzzle is on screen."""

    model_config = ConfigDict(extra="allow")

    background: Image
    piece: Piece


def capture_puzzle(
    session: Session,
    challenge_id: str | None,
    *,
    n: int | None = None,
    seconds: float | None = None,
) -> None:
    """Save the puzzle's two images and its geometry. Any failure is recorded, never raised.

    The bytes are also kept in `session.capture` for the solver. A retry for the same puzzle
    passes its `n` and a longer `seconds`.
    """
    ctx, driver = session.ctx, session.driver
    if n is None:
        session.puzzles += 1
        n = session.puzzles
    try:
        info = PuzzleInfo.model_validate(
            wait_for(
                session,
                lambda: driver.execute_script(PUZZLE_INFO_JS, session.puzzle_srcs),
                session.timeouts.puzzle_images if seconds is None else seconds,
                "puzzle_images",
            )
        )
        srcs = [info.background.src, info.piece.src]
        session.puzzle_srcs.extend(srcs)
        background, piece = fetch_in_page(session, srcs)
        saved = {
            part: save_fetched(ctx, f"puzzle-{n}-{part}", file)
            for part, file in (("background", background), ("piece", piece))
        }
        session.capture = CapturedPuzzle(
            n, challenge_id, background.data, piece.data, pixels(info.piece)
        )
        ctx.event(
            "puzzle_captured",
            {"challenge_id": challenge_id, "n": n, "artifacts": saved, **info.model_dump()},
        )
    except Exception as error:  # noqa: BLE001 - a missing capture must not change the result
        ctx.event(
            "puzzle_capture_failed",
            {"challenge_id": challenge_id, "n": n, "error": describe(error)},
        )


def pixels(piece: Piece) -> int | None:
    """The piece's inline `top` (like '60px') as a number, or None."""
    try:
        return round(float(piece.style_top.removesuffix("px")))
    except ValueError:
        return None
