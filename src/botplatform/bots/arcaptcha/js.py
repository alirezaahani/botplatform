"""JavaScript run in the page, and the CSS selectors of the slider."""

# The slider handle and the puzzle piece. Both were seen in captured DOM data and confirmed live.

# Reads the challenge ID three ways, separately, so each answer stays distinct. The widget list is
# `window.arcaptcha.widgets`, keyed by widget ID (from widget.arcaptcha.ir/1/api.js).
WIDGET_CHALLENGE_ID_JS = """
const attempt = (read) => {
  try { return {value: read() || null}; } catch (error) { return {error: String(error)}; }
};
const arc = window.arcaptcha;
const widgets = arc && arc.widgets ? arc.widgets : null;
const ids = widgets ? Object.keys(widgets) : [];
const widget = ids.length ? widgets[ids[0]] : null;
const hidden = document.querySelector('#arcaptcha-token');
return {
  arcaptcha_present: !!arc,
  widget_ids: ids,
  widget_has_get_challenge_id: !!widget && typeof widget.getChallengeID === 'function',
  widget_value: widget && typeof widget.getChallengeID === 'function'
    ? attempt(() => widget.getChallengeID()) : null,
  get_arc_token: arc && typeof arc.getArcToken === 'function' && ids.length
    ? attempt(() => arc.getArcToken(ids[0])) : null,
  hidden_field: hidden ? {value: hidden.value || null} : null
};
"""
# Screenshots must never show the password, so the field is blanked first.
BLANK_PASSWORD_JS = "document.querySelectorAll('input[type=password]').forEach(e => e.value = '')"
# What the site could learn about the browser, stored as is. The demo's credentials are public,
# and these values are the evidence for which profile helps. It is async because of the
# permissions query, so it ends by calling the callback that `execute_async_script` provides.
BROWSER_SIGNALS_JS = """
const done = arguments[arguments.length - 1];
const attempt = (read) => {
  try { return read(); } catch (error) { return {error: String(error)}; }
};
const webgl = attempt(() => {
  const gl = document.createElement('canvas').getContext('webgl');
  if (!gl) return null;
  const info = gl.getExtension('WEBGL_debug_renderer_info');
  if (!info) return {vendor: null, renderer: null};
  return {
    vendor: gl.getParameter(info.UNMASKED_VENDOR_WEBGL),
    renderer: gl.getParameter(info.UNMASKED_RENDERER_WEBGL)
  };
});
const signals = {
  webdriver: navigator.webdriver,
  user_agent: navigator.userAgent,
  platform: navigator.platform,
  languages: Array.from(navigator.languages || []),
  plugins: navigator.plugins.length,
  mime_types: navigator.mimeTypes.length,
  hardware_concurrency: navigator.hardwareConcurrency,
  device_memory: navigator.deviceMemory === undefined ? null : navigator.deviceMemory,
  chrome: {
    present: typeof window.chrome !== 'undefined',
    runtime: !!(window.chrome && window.chrome.runtime),
    csi: !!(window.chrome && window.chrome.csi)
  },
  window: {
    outer_width: window.outerWidth, outer_height: window.outerHeight,
    inner_width: window.innerWidth, inner_height: window.innerHeight
  },
  screen: {width: screen.width, height: screen.height},
  notification_permission: typeof Notification === 'undefined' ? null : Notification.permission,
  webgl: webgl,
  automation_properties: attempt(() => Object.getOwnPropertyNames(window).filter(
    (name) => /^\\$?cdc_/.test(name) || /selenium|webdriver/i.test(name)
  ))
};
if (!navigator.permissions || !navigator.permissions.query) {
  signals.permissions_notifications = null;
  done(signals);
} else {
  navigator.permissions.query({name: 'notifications'}).then(
    (status) => { signals.permissions_notifications = status.state; done(signals); },
    (error) => { signals.permissions_notifications = {error: String(error)}; done(signals); }
  );
}
"""
# The puzzle's images. The piece is `img.puzzle` and the background is the other image whose src
# has `/puzzles/` (both seen in the real DOM). The slider's selectors are NOT known, so instead of
# inventing one this lists elements whose class name mentions slider, handle, track or drag, and
# always records the piece's parent. A src already in `seen` belongs to an earlier puzzle.
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
  slider_candidates: Array.from(document.querySelectorAll('[class*=slider i], [class*=handle i], '
    + '[class*=track i], [class*=drag i]')).filter((el) => el !== piece).slice(0, 10).map(
    (el) => ({tag: el.tagName.toLowerCase(), class: String(el.className), rect: rect(el)})
  ),
  device_pixel_ratio: window.devicePixelRatio
};
"""
# Downloads the two images from inside the page, so the request has the browser's origin and
# cookies. Returns base64 for each, plus the response's content type.
FETCH_IMAGES_JS = """
const done = arguments[arguments.length - 1];
const get = async (src) => {
  const response = await fetch(src);
  if (!response.ok) throw new Error('HTTP ' + response.status);
  const bytes = new Uint8Array(await response.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return {b64: btoa(binary), content_type: response.headers.get('content-type')};
};
Promise.all([get(arguments[0]), get(arguments[1])]).then(
  (images) => done({background: images[0], piece: images[1]}),
  (error) => done({error: String(error)})
);
"""
