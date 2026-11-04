"""Scripts and the plan for the drag probe (`arcaptcha-drag-probe`).

The probe measures how a synthetic drag of the slider handle maps to the piece position and to
the `answers` value. Nothing here is verified against the real site: the handle is assumed to be
`div.draggable` and the piece `img.puzzle`, both seen in captured DOM data.
"""

HANDLE = "div.draggable"
PIECE = "img.puzzle"

# (method, dx in px). Methods alternate; the last dx values deliberately over-travel the handle
# (about 196 px of travel was seen) to find the clamp.
DRAG_DX = [40, 80, 120, 150, 180, 200, 240, 300]
METHODS = ("selenium", "cdp")
STEPS = 8  # moves per drag
STEP_PAUSE = 0.03  # seconds between moves

EVENT_TYPES = [
    "mousedown", "mousemove", "mouseup",
    "pointerdown", "pointermove", "pointerup",
    "touchstart", "touchmove", "touchend",
    "dragstart", "drag", "dragend", "dragover", "drop",
]  # fmt: skip


def plan(attempts: int) -> list[tuple[str, int]]:
    """The first `attempts` planned attempts as (method, dx), methods alternating."""
    return [(METHODS[i % len(METHODS)], DRAG_DX[i % len(DRAG_DX)]) for i in range(attempts)]


# Installed once per page (guarded by a window property). Per event type: a count, the first few
# `isTrusted` values and the first few targets. Reading returns the summary and starts it over, so
# each attempt gets its own. The lists are capped, so the summary stays small.
INSTALL_LISTENER_JS = (
    """
const types = %s;
if (!window.__dragProbe) {
  const state = {summary: {}};
  window.__dragProbe = state;
  for (const type of types) {
    document.addEventListener(type, (event) => {
      const entry = state.summary[type] || (state.summary[type] = {count: 0, trusted: [], targets: []});
      entry.count += 1;
      if (entry.trusted.length < 5) entry.trusted.push(event.isTrusted);
      const t = event.target;
      const label = t && t.tagName ? t.tagName.toLowerCase() + '.' + String(t.className).slice(0, 80) : String(t);
      if (entry.targets.length < 3 && !entry.targets.includes(label)) entry.targets.push(label);
    }, true);
  }
}
return true;
"""
    % EVENT_TYPES
)
READ_LISTENER_JS = """
const state = window.__dragProbe;
if (!state) return null;
const summary = state.summary;
state.summary = {};
return summary;
"""

# The handle and the piece right now: rects, inline and computed left, and any transform. The
# piece's parent is included because the widget may move that instead of the image.
SAMPLE_JS = """
const rect = (el) => {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {x: r.x, y: r.y, width: r.width, height: r.height};
};
const look = (el) => {
  if (!el) return null;
  const c = getComputedStyle(el);
  return {rect: rect(el), style_left: el.style.left, style_transform: el.style.transform,
          computed_left: c.left, computed_transform: c.transform};
};
const handle = document.querySelector(arguments[0]);
const piece = document.querySelector(arguments[1]);
return {handle: look(handle), piece: look(piece), piece_parent: look(piece && piece.parentElement)};
"""
