"""JavaScript that runs in the page, and the Python that goes with it. Not tied to one site."""

import base64
import mimetypes
from dataclasses import dataclass

from botplatform.bots.utils.browser import BrowserSession, describe, do
from botplatform.contract import RunContext

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
# Downloads files from inside the page, so each request has the browser's origin and cookies.
# Takes an array of URLs and returns a list with base64 and the content type of each, in order.
FETCH_FILES_JS = """
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
Promise.all(arguments[0].map(get)).then(done, (error) => done({error: String(error)}));
"""


def record_browser_signals(session: BrowserSession) -> None:
    try:
        signals = do(session, lambda: session.driver.execute_async_script(BROWSER_SIGNALS_JS))
    except Exception as error:  # noqa: BLE001 - evidence gathering must not change the result
        signals = {"error": describe(error)}
    session.ctx.event("browser_signals", signals if isinstance(signals, dict) else {})


@dataclass(frozen=True)
class FetchedFile:
    data: bytes
    content_type: str | None


def fetch_in_page(session: BrowserSession, urls: list[str]) -> list[FetchedFile]:
    """Download `urls` from inside the page, in order. Raises RuntimeError if the page fails."""
    fetched = do(session, lambda: session.driver.execute_async_script(FETCH_FILES_JS, urls))
    if fetched is None or isinstance(fetched, dict):
        raise RuntimeError((fetched or {}).get("error", "no result"))
    return [FetchedFile(base64.b64decode(f["b64"]), f["content_type"]) for f in fetched]


def save_fetched(ctx: RunContext, stem: str, fetched: FetchedFile) -> str:
    """Save the file as an artifact named `stem` plus an extension for its type. Returns the name."""
    content_type = (fetched.content_type or "").split(";")[0].strip()
    extension = mimetypes.guess_extension(content_type)
    if not extension:  # no header, or a type Python does not know
        content_type, extension = "application/octet-stream", ".bin"
    name = f"{stem}{extension}"
    ctx.artifact(name, content_type, fetched.data)
    return name
