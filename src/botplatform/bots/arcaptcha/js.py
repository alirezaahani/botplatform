"""JavaScript run in the ARCaptcha page."""

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
