"""The ARCaptcha demo bot: tick the checkbox, read `challenge_id`, log in, verify the result.

Puzzle capture (data for a future slider solver): when a `create` of type `puzzle` arrives and its
two images are on screen, the scenario saves them as artifacts `puzzle-<n>-background.<ext>` and
`puzzle-<n>-piece.<ext>` and records a `puzzle_captured` event (n counts puzzles in the run from 1).
Events are appended in order, so the `answer_request` events that follow a `puzzle_captured`
event, up to the next one, belong to puzzle n; the `answer` record itself is unchanged. A failed
capture records `puzzle_capture_failed` and never changes the run's result.
"""

import base64
import json
import os
import random
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar
from urllib.parse import urlsplit

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By

from botplatform.bots import drag_probe
from botplatform.bots.arcaptcha_codec import decode_body
from botplatform.bots.selenium_support import (
    CapturedResponse,
    ResponseWatcher,
    call_handling_alerts,
    chrome,
)
from botplatform.contract import Bot, BotResult, RunContext, Status
from botplatform.profiles import (
    ALL_SIGNALS,
    ALL_SIGNALS_HEADLESS,
    BASELINE,
    PROFILES,
    Profile,
    bot_id,
)
from botplatform.solver import gap, movement

DEMO_URL = "https://demo.arcaptcha.co/"
CHECKBOX = "#input-checkbox"
TOAST = ".Vue-Toastification__toast"
# vue-toastification adds `Vue-Toastification__toast--<type>`; the demo calls `success` or `error`.
TOAST_SUCCESS = "Vue-Toastification__toast--success"
TOAST_ERROR = "Vue-Toastification__toast--error"
LOGIN_BUTTON = "//button[normalize-space()='Login']"
CHALLENGE_TYPES = {"puzzle", "question", "2fa"}
ACCEPTED_TYPES = {"accept", "cookie"}

POLL_SECONDS = 0.25


@dataclass(frozen=True)
class StepTimeouts:
    """Seconds allowed for each step. The defaults stay well below the run time limit."""

    load_page: float = 30
    find_checkbox: float = 15
    create_response: float = 20
    more_create_responses: float = 2
    login_response: float = 15
    toast: float = 5
    # Only for a bot that waits for a person to solve the puzzle. The wait leaves room in the 180 s
    # run limit for the page load (~8 s) and the login (~10 s). A rejected answer brings a new
    # puzzle quickly, so if no `create` follows an `answer` within `answer_settle`, we take the
    # puzzle as finished (a guess the live experiment checks).
    person_wait: float = 130
    answer_settle: float = 3
    # How long a captured puzzle's two images get to load after its `create` arrives.
    puzzle_images: float = 5
    # Only for the automatic solver. `puzzle_ready` is how long a puzzle's handle and images get
    # to appear (the first puzzle's images came late live). A run makes at most `solve_attempts`
    # answers; a handle that did not move at all is pressed again on the same puzzle up to
    # `stuck_retries` times, and that does not count as an attempt.
    puzzle_ready: float = 20
    solve_attempts: int = 3
    stuck_retries: int = 2


DEFAULT_TIMEOUTS = StepTimeouts()


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


def redact(text: str, password: str, keep: str) -> str:
    """Replace the password everywhere except inside `keep`, such as the site's host name.

    A short password like `demo` would otherwise turn `demo.arcaptcha.co` into nonsense.
    Anywhere else, even a match followed by a dot, is replaced: over-redacting is fine.
    """
    if not keep:
        return text.replace(password, "[password]")
    return keep.join(part.replace(password, "[password]") for part in text.split(keep))


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
IMAGE_TYPES = [
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF8", "image/gif", "gif"),
]


def sniff_image(data: bytes, header: str | None) -> tuple[str, str]:
    """The content type and file extension of image bytes, from their first bytes."""
    for magic, content_type, extension in IMAGE_TYPES:
        if data.startswith(magic):
            return content_type, extension
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if header and header.startswith("image/"):
        content_type = header.split(";")[0].strip()
        return content_type, content_type.split("/")[1].split("+")[0]
    return "application/octet-stream", "bin"


@dataclass
class CapturedPuzzle:
    """One puzzle's images as fetched in the page, and the piece's inline `top` in px."""

    n: int
    challenge_id: str | None
    background: bytes
    piece: bytes
    piece_top: int | None


class StepTimeout(Exception):
    """A step ran out of time. `step` becomes the run's reason."""

    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step


class ArcaptchaBot(Bot):
    id = "arcaptcha"
    name = "ARCaptcha demo (Selenium)"
    description = (
        "Ticks the checkbox on demo.arcaptcha.co, records challenge_id, logs in and checks that "
        "the login really succeeded."
    )
    modes: ClassVar[list[str]] = ["headless", "headful"]
    profile: ClassVar[Profile] = BASELINE
    # A profile for a mode, where `profile` is not right for every mode. Not listed: `profile`.
    profile_by_mode: ClassVar[dict[str, Profile]] = {}
    wait_for_person: ClassVar[bool] = False
    solve_with: ClassVar[tuple[str, str] | None] = None  # (finder name, mover name)

    def __init__(
        self,
        url: str = DEMO_URL,
        timeouts: StepTimeouts = DEFAULT_TIMEOUTS,
        profile: Profile | None = None,
    ) -> None:
        self.url = url
        self.timeouts = timeouts
        self.profile = profile or type(self).profile
        self._given_profile = profile  # a profile passed in wins over the one for the mode

    def profile_for(self, mode: str) -> Profile:
        """The browser profile for `mode`: the one passed in, else the class's for that mode."""
        return self._given_profile or type(self).profile_by_mode.get(mode, self.profile)

    def run(self, ctx: RunContext) -> BotResult:
        username = os.environ.get("ARCAPTCHA_USERNAME")
        password = os.environ.get("ARCAPTCHA_PASSWORD")
        if not username or not password:
            return BotResult(
                Status.ERROR,
                "missing_credentials",
                "Set ARCAPTCHA_USERNAME and ARCAPTCHA_PASSWORD in .env",
            )
        try:
            profile = self.profile_for(ctx.mode)
            with chrome(headless=ctx.mode == "headless", profile=profile) as driver:
                scenario = Scenario(
                    ctx,
                    driver,
                    username,
                    password,
                    self.url,
                    self.timeouts,
                    profile,
                    self.wait_for_person,
                    self.solve_with,
                )
                return scenario.run()
        except Exception:  # noqa: BLE001 - every failure becomes an error result
            # The password must never reach the run's error field, whatever the exception says.
            host = urlsplit(self.url).hostname or ""
            details = redact(traceback.format_exc(), password, host)
            return BotResult(Status.ERROR, "unhandled_exception", details)


class ArcaptchaAssistedBot(ArcaptchaBot):
    """A diagnostic: does the site accept a correct answer from this browser?

    A person solves the puzzle in the live viewer, so the run is never a bot success. Nothing
    solves the slider yet, and before building a solver we want to see an accepted answer.
    """

    id = "arcaptcha-assisted"
    name = "ARCaptcha demo (a person solves the puzzle)"
    description = (
        "A diagnostic, not an automatic bot. Ticks the checkbox like the others, and if the site "
        "shows a puzzle, waits for a person to solve it in the live viewer (headful only), records "
        "the answer request and response, then logs in. A verified login ends as success with the "
        "reason human_solved, because a person did the solving."
    )
    modes: ClassVar[list[str]] = ["headful"]
    profile = ALL_SIGNALS
    wait_for_person = True


def solver_bot(finder: str, mover: str) -> type[ArcaptchaBot]:
    """An automatic solver bot, `arcaptcha-solver-<finder>-<mover>`.

    The finder and mover names are keys of `gap.FINDERS` and `movement.MOVERS`.
    """
    return type(
        f"ArcaptchaSolver{finder.title()}{mover.title()}Bot",
        (ArcaptchaBot,),
        {
            "id": f"arcaptcha-solver-{finder}-{mover}",
            "name": f"ARCaptcha demo (automatic solver: {finder} finder, {mover} movement)",
            "description": (
                "An automatic solver. Ticks the checkbox and, when a puzzle appears, finds the gap "
                f"with the '{finder}' finder and drags the handle there with '{mover}' movement "
                "(Selenium ActionChains), up to 3 answers per run, then logs in. A verified login "
                "ends as success with the reason solved. If no gap is found the run ends as "
                "blocked / gap_not_found, and after 3 rejected answers as blocked / solve_failed. "
                "Headful uses the all-signals profile and headless the all-signals-headless one."
            ),
            "modes": ["headless", "headful"],
            "profile": ALL_SIGNALS,
            "profile_by_mode": {"headful": ALL_SIGNALS, "headless": ALL_SIGNALS_HEADLESS},
            "solve_with": (finder, mover),
        },
    )


SOLVER_BOTS: list[type[ArcaptchaBot]] = [
    solver_bot("cv", "linear"),
    solver_bot("cv", "eased"),
    solver_bot("silhouette", "linear"),
    solver_bot("silhouette", "eased"),
]


def profile_bot(profile: Profile) -> type[ArcaptchaBot]:
    """A bot class that runs the ARCaptcha scenario with `profile`, as `arcaptcha-<name>`.

    One bot per profile makes the run history the evidence: a bot's runs are one profile's runs.
    """
    return type(
        "Arcaptcha" + profile.name.title().replace("-", "") + "Bot",
        (ArcaptchaBot,),
        {
            "id": bot_id(profile.name),
            "name": f"ARCaptcha demo (Selenium, {profile.name})",
            "description": f"{ArcaptchaBot.description} Browser profile: {profile.description}",
            "profile": profile,
        },
    )


# The baseline is `ArcaptchaBot` itself, so its id, name and description stay as they were.
PROFILE_BOTS: list[type[ArcaptchaBot]] = [
    profile_bot(p) for p in PROFILES.values() if p.name != BASELINE.name
]


class Scenario:
    def __init__(
        self,
        ctx: RunContext,
        driver: webdriver.Chrome,
        username: str,
        password: str,
        url: str = DEMO_URL,
        timeouts: StepTimeouts = DEFAULT_TIMEOUTS,
        profile: Profile = BASELINE,
        wait_for_person: bool = False,
        solve_with: tuple[str, str] | None = None,
    ) -> None:
        self.ctx = ctx
        self.profile = profile
        self.wait_for_person = wait_for_person
        self.solve_with = solve_with
        self.rng = random.Random()
        self.solved = False  # the solver's answer was accepted
        self.capture: CapturedPuzzle | None = None  # the current puzzle's bytes, if captured
        self.answer_records: list[dict[str, Any]] = []  # every `answer` exchange, in order
        self.driver = driver
        self.username = username
        self.password = password
        self.url = url
        self.timeouts = timeouts
        self.watcher = ResponseWatcher(
            driver,
            {
                "create": lambda url: url.split("?")[0].endswith("/api/create"),
                "login": lambda url: url.split("?")[0].endswith("/api/login"),
                "answer": lambda url: url.split("?")[0].endswith("/arcaptcha/api/answer"),
            },
            # Not `login`, which holds the password. `create` carries the browser signals, and
            # `answer` is kept because nobody has seen a decoded one yet.
            capture_requests=frozenset({"create", "answer"}),
        )
        self.creates: list[dict[str, Any]] = []
        self.logins: list[CapturedResponse] = []
        # When the latest `answer` arrived, unless a new `create` followed it.
        self.answered_at: float | None = None
        self.person_solved = False
        self.pending_puzzle: tuple[str | None] | None = None  # set by a `create`, taken by `_drain`
        self.puzzles = 0  # puzzles seen so far, captured or not
        self.puzzle_srcs: list[str] = []  # image srcs already taken, to tell a new puzzle apart

    def run(self) -> BotResult:
        try:
            return self._run()
        except StepTimeout as timeout:
            self._screenshot(f"timeout-{timeout.step}")
            return BotResult(Status.TIMEOUT, timeout.step, f"Timed out in step '{timeout.step}'")
        except Exception:
            self._screenshot("error")
            raise

    def _run(self) -> BotResult:
        self.ctx.event("browser_profile", self.profile.settings())
        earlier = self._open_and_tick()
        self._screenshot("after-click")
        # Decision 3b: the login is always attempted, but it can never upgrade an earlier failure.
        try:
            verdict = self._log_in()
        except StepTimeout as timeout:
            if earlier:
                self.ctx.event("login_timeout", {"step": timeout.step})
                self._screenshot("login-timeout")
                return earlier
            raise
        except Exception as error:
            if not earlier:
                raise
            self.ctx.event("login_error", {"type": type(error).__name__})
            self._screenshot("login-error")
            return earlier
        self._screenshot("after-login")
        # Both steps found nothing wrong, so this is the only place a run can succeed.
        if self.solved:
            return earlier or verdict or BotResult(Status.SUCCESS, "solved")
        if self.person_solved:
            # Not a bot success: a person did the solving. The reason keeps it out of bot counts.
            return earlier or verdict or BotResult(Status.SUCCESS, "human_solved")
        return earlier or verdict or BotResult(Status.SUCCESS)

    # -- Steps -------------------------------------------------------------------------------

    def _open_and_tick(self) -> BotResult | None:
        """Tick the checkbox. Return the failure this causes, or None if the widget accepted us."""
        driver = self.driver
        driver.set_page_load_timeout(self.timeouts.load_page)
        try:
            self._do(lambda: driver.get(self.url))
        except TimeoutException:
            raise StepTimeout("load_page") from None
        self.ctx.event("page_loaded", {"iframes": len(driver.find_elements(By.TAG_NAME, "iframe"))})
        self._record_browser_signals()
        self._wait_for(
            lambda: driver.find_elements(By.CSS_SELECTOR, CHECKBOX),
            self.timeouts.find_checkbox,
            "find_checkbox",
        )
        self._screenshot("before-click")
        self.ctx.event("widget_challenge_id_before_click", self._widget_challenge_id())
        self._do(lambda: driver.find_element(By.CSS_SELECTOR, CHECKBOX).click(), retry=False)
        self.ctx.event("checkbox_clicked")

        # A request that failed will never get a response, so there is nothing more to wait for.
        self._wait_for(
            lambda: self._drain() or "create" in self.watcher.failed,
            self.timeouts.create_response,
            "create_response",
        )
        # A later `create` can follow, so keep listening briefly.
        deadline = time.monotonic() + self.timeouts.more_create_responses
        while time.monotonic() < deadline:
            self._do(self._drain)
            time.sleep(POLL_SECONDS)
        self.ctx.event("widget_challenge_id_after_click", self._widget_challenge_id())
        self.ctx.event(
            "create_requests",
            {
                "post_requests_started": self.watcher.started.count("create"),
                "failed": self.watcher.failed.count("create"),
                "responses": len(self.creates),
                "not_counted": [r for r in self.watcher.ignored if r["name"] == "create"],
            },
        )
        result = self._classify_create()
        unsolved = BotResult(Status.BLOCKED, "challenge_unsolved")
        if self.wait_for_person and result == unsolved and self._types()[-1] == "puzzle":
            return self._wait_for_person()
        if self.solve_with and result == unsolved and self._types()[-1] == "puzzle":
            return self._run_solver()
        return result

    def _wait_for_person(self) -> BotResult | None:
        """Wait while a person solves the puzzle, then go on to the login.

        Every `answer` and later `create` is recorded by `_drain`. The answer's body is never read
        to decide anything: the login is the judge. Like any step timeout, running out of time
        ends the run without a login.
        """
        wait = self.timeouts.person_wait
        self.ctx.event(
            "waiting_for_person",
            {"seconds": wait, "challenge_id": self.creates[-1]["challenge_id"]},
        )
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            self._do(self._drain)
            if self._types()[-1:] != ["puzzle"]:
                return self._classify_create()  # a block or an accept, handled as usual
            if (
                self.answered_at is not None
                and time.monotonic() - self.answered_at >= self.timeouts.answer_settle
            ):
                self.person_solved = True
                return None
            time.sleep(POLL_SECONDS)
        raise StepTimeout("human_wait_expired")

    def _run_solver(self) -> BotResult | None:
        """Solve the puzzle: find the gap, drag the handle there, up to `solve_attempts` times.

        The answer's body never decides the outcome beyond what `_wait_for_person` also does: an
        answer followed by no new puzzle within `answer_settle` is taken as accepted, and the
        login is the judge. Returns None for that, so the login runs.
        """
        timeouts = self.timeouts
        finder_name, mover_name = self.solve_with or ("", "")
        self.ctx.event(
            "solve_started",
            {
                "finder": finder_name,
                "mover": mover_name,
                "attempts": timeouts.solve_attempts,
                "stuck_retries": timeouts.stuck_retries,
                "puzzle_ready": timeouts.puzzle_ready,
            },
        )
        try:
            result = self._solve_loop(finder_name, mover_name)
        except StepTimeout as timeout:
            self.ctx.event("solve_finished", {"reason": timeout.step})
            raise
        return result

    def _solve_loop(self, finder_name: str, mover_name: str) -> BotResult | None:
        timeouts = self.timeouts
        attempts = 0
        while attempts < timeouts.solve_attempts:
            self._do(self._drain)
            if self._types()[-1:] != ["puzzle"]:
                self.ctx.event("solve_finished", {"reason": "not_a_puzzle", "attempts": attempts})
                return self._classify_create()
            puzzle = self._puzzle_ready()
            attempts += 1
            attempt: dict[str, Any] = {
                "n": attempts,
                "puzzle": puzzle.n,
                "challenge_id": puzzle.challenge_id,
                "finder": finder_name,
                "target_x": None,
                "mover": mover_name,
                "dx": None,
                "duration": None,
                "steps": None,
                "stuck_retries": 0,
                "outcome": None,
                "handle_left": None,
                "piece_left": None,
            }
            try:
                target = gap.FINDERS[finder_name](
                    puzzle.background, puzzle.piece, puzzle.piece_top or 0
                )
            except gap.GapNotFound as error:
                attempt["outcome"] = "gap_not_found"
                attempt["message"] = str(error)[:200]
                self.ctx.event("solve_attempt", attempt)
                self.ctx.event("solve_finished", {"reason": "gap_not_found", "attempts": attempts})
                return BotResult(Status.BLOCKED, "gap_not_found")
            attempt["target_x"] = target
            attempt["dx"] = target
            answers_before = len(self.answer_records)
            drag = None
            try:
                while True:
                    path = movement.MOVERS[mover_name](target, self.rng)
                    attempt["duration"] = round(movement.duration(path), 3)
                    attempt["steps"] = len(path)
                    handle = self._handle()
                    drag = movement.perform_drag(self.driver, handle, path, self._do)
                    if drag.moved or attempt["stuck_retries"] >= timeouts.stuck_retries:
                        break
                    attempt["stuck_retries"] += 1
                    self._release_everything()
            except Exception as error:  # noqa: BLE001 - one failed drag must not stop the run
                attempt["error"] = f"{type(error).__name__}: {str(error).splitlines()[0][:200]}"
                self._release_everything()
            if drag is not None:
                attempt["handle_left"] = drag.handle_left
                attempt["piece_left"] = drag.piece_left
            outcome = self._await_next_puzzle(puzzle.n, answers_before)
            attempt["outcome"] = {
                "next_puzzle": "rejected",
                "no_new_puzzle": "accepted",
                "no_answer": "no_answer",
            }[outcome]
            self.ctx.event("solve_attempt", attempt)
            if attempt["outcome"] == "accepted":
                self.solved = True
                self.ctx.event("solve_finished", {"reason": "solved", "attempts": attempts})
                return None
        self.ctx.event("solve_finished", {"reason": "solve_failed", "attempts": attempts})
        return BotResult(Status.BLOCKED, "solve_failed")

    def _handle(self) -> Any:
        found = self._wait_for(
            lambda: [
                e
                for e in self.driver.find_elements(By.CSS_SELECTOR, drag_probe.HANDLE)
                if e.is_displayed()
            ],
            self.timeouts.puzzle_ready,
            "puzzle_ready",
        )
        return found[0]

    def _puzzle_ready(self) -> CapturedPuzzle:
        """The current puzzle with its handle on screen and its images in hand, or StepTimeout."""
        deadline = time.monotonic() + self.timeouts.puzzle_ready
        self._handle()
        while self.capture is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self.puzzles == 0:
                raise StepTimeout("puzzle_ready")
            challenge_id = self.creates[-1]["challenge_id"]
            self._capture_puzzle(challenge_id, n=self.puzzles, seconds=remaining)
        return self.capture

    def _release_everything(self) -> None:
        """After a failed drag, let go of the mouse so the next attempt starts clean."""
        try:
            ActionChains(self.driver).reset_actions()
            self.driver.execute_cdp_cmd(
                "Input.dispatchMouseEvent",
                {"type": "mouseReleased", "x": 0, "y": 0, "button": "left", "clickCount": 1},
            )
        except Exception:  # noqa: BLE001 - best effort only
            pass

    def _await_next_puzzle(self, n: int, answers_before: int) -> str:
        """Drain until the answer and then the next puzzle's capture arrive (or time runs out)."""
        settle = self.timeouts.answer_settle
        deadline = time.monotonic() + settle
        while len(self.answer_records) == answers_before:
            if time.monotonic() >= deadline:
                return "no_answer"
            self._do(self._drain)
            time.sleep(POLL_SECONDS)
        deadline = time.monotonic() + settle
        while self.puzzles == n:
            if time.monotonic() >= deadline:
                return "no_new_puzzle"
            self._do(self._drain)
            time.sleep(POLL_SECONDS)
        return "next_puzzle"

    def _log_in(self) -> BotResult | None:
        """Submit the form. Return a failure if the result is not confirmed by both signals."""
        driver = self.driver
        self._do(lambda: driver.find_element(By.ID, "email").send_keys(self.username), retry=False)
        self._do(
            lambda: driver.find_element(By.ID, "password").send_keys(self.password), retry=False
        )
        self.ctx.event("login_submitted")
        self._do(lambda: driver.find_element(By.XPATH, LOGIN_BUTTON).click(), retry=False)

        self._wait_for(
            lambda: (self._drain() and self.logins) or "login" in self.watcher.failed,
            self.timeouts.login_response,
            "login_response",
        )
        if not self.logins:
            self.ctx.event("login_request_failed")
            return BotResult(
                Status.ERROR, "login_request_failed", "The login request failed before a response"
            )
        login = self.logins[-1]
        body = self._json_body(login)
        self.ctx.event(
            "login_response", {"http_status": login.status, "body": self._body_text(login)}
        )

        # The response has arrived, so a missing toast is a disagreement, not a timeout.
        try:
            toast = self._wait_for(self._toast, self.timeouts.toast, "toast")
        except StepTimeout:
            toast = {"kind": "none", "text": ""}
        self.ctx.event("toast", toast)
        message = body.get("msg") if isinstance(body, dict) else None
        confirmed = (
            login.status == 200
            and toast["kind"] == "success"
            and isinstance(message, str)
            and message in toast["text"]
        )
        if confirmed:
            return None
        return BotResult(
            Status.FAILED,
            "verification_failed",
            f"Login returned HTTP {login.status} and the toast was '{toast['kind']}'",
        )

    # -- Helpers -----------------------------------------------------------------------------

    def _do(self, action: Callable[[], Any], *, retry: bool = True) -> Any:
        """Run any driver call. A JS `alert()` is recorded and dismissed instead of crashing it."""

        def on_alert(text: str) -> None:
            self.ctx.event("alert", {"text": text})

        return call_handling_alerts(self.driver, action, on_alert, retry=retry)

    def _wait_for(self, check: Callable[[], Any], seconds: float, step: str) -> Any:
        deadline = time.monotonic() + seconds
        while True:
            result = self._do(check)
            if result:
                return result
            if time.monotonic() >= deadline:
                raise StepTimeout(step)
            time.sleep(POLL_SECONDS)

    def _drain(self) -> bool:
        """Read new network responses. Each `create` is recorded the moment it is seen."""
        # Reading the network log never notices a JS `alert()`, and an open alert freezes the
        # page. Any other driver command raises when one is open, which `_do` then handles.
        self.driver.title  # noqa: B018
        seen_create = False
        for response in self.watcher.poll():
            if response.name == "login":
                self.logins.append(response)
            elif response.name == "answer":
                self.answered_at = time.monotonic()
                record = self._exchange_record(response)
                self.answer_records.append(record)
                self.ctx.event("answer_request", record)
            else:
                self._handle_create(response)
                seen_create = True
        if self.pending_puzzle is not None:
            # Once per poll, for the latest puzzle: if two `create`s arrive together, the page
            # shows only the second puzzle, so the first has nothing left to capture.
            (challenge_id,), self.pending_puzzle = self.pending_puzzle, None
            self._capture_puzzle(challenge_id)
        return seen_create or bool(self.logins)

    def _handle_create(self, response: CapturedResponse) -> None:
        info: dict[str, Any] = {"http_status": response.status, "captcha_type": None}
        challenge_id = None
        if response.body is None:
            info["body_error"] = response.body_error
        else:
            try:
                decoded = decode_body(response.body)
                info["captcha_type"] = decoded.get("captcha_type")
                challenge_id = (decoded.get("content") or {}).get("challenge_id")
            except (ValueError, AttributeError, TypeError) as error:
                info["decode_error"] = type(error).__name__
        if not isinstance(challenge_id, str) or not challenge_id:
            challenge_id = None
        self.ctx.event("create_request", self._exchange_record(response))
        self.creates.append({"captcha_type": info["captcha_type"], "challenge_id": challenge_id})
        info["has_challenge_id"] = challenge_id is not None
        if challenge_id:
            self.ctx.record_challenge_id(challenge_id)
        self.capture = None
        self.answered_at = None  # a new puzzle after an answer means the answer was not final
        self.ctx.event("create_response", info)
        self.pending_puzzle = (challenge_id,) if info["captcha_type"] == "puzzle" else None

    def _capture_puzzle(
        self, challenge_id: str | None, *, n: int | None = None, seconds: float | None = None
    ) -> None:
        """Save the puzzle's two images and its geometry. Any failure is recorded, never raised.

        The bytes are also kept in `self.capture` for the solver. A retry for the same puzzle
        passes its `n` and a longer `seconds`.
        """
        if n is None:
            self.puzzles += 1
            n = self.puzzles
        try:
            info = self._wait_for(
                lambda: self.driver.execute_script(PUZZLE_INFO_JS, self.puzzle_srcs),
                self.timeouts.puzzle_images if seconds is None else seconds,
                "puzzle_images",
            )
            srcs = [info["background"]["src"], info["piece"]["src"]]
            self.puzzle_srcs.extend(srcs)
            fetched = self._do(lambda: self.driver.execute_async_script(FETCH_IMAGES_JS, *srcs))
            if not isinstance(fetched, dict) or "error" in fetched:
                raise RuntimeError((fetched or {}).get("error", "no result"))
            saved = {}
            raw: dict[str, bytes] = {}
            for part in ("background", "piece"):
                data = base64.b64decode(fetched[part]["b64"])
                raw[part] = data
                content_type, extension = sniff_image(data, fetched[part]["content_type"])
                name = f"puzzle-{n}-{part}.{extension}"
                self.ctx.artifact(name, content_type, data)
                saved[part] = name
            self.capture = CapturedPuzzle(
                n, challenge_id, raw["background"], raw["piece"], self._pixels(info["piece"])
            )
            self.ctx.event(
                "puzzle_captured",
                {"challenge_id": challenge_id, "n": n, "artifacts": saved, **info},
            )
        except Exception as error:  # noqa: BLE001 - a missing capture must not change the result
            message = str(error).splitlines()[0][:200] if str(error) else ""
            self.ctx.event(
                "puzzle_capture_failed",
                {
                    "challenge_id": challenge_id,
                    "n": n,
                    "type": type(error).__name__,
                    "message": message,
                },
            )

    @staticmethod
    def _pixels(piece: dict[str, Any]) -> int | None:
        """The piece's inline `top` (like '60px') as a number, or None."""
        try:
            return round(float(str(piece.get("style_top", "")).removesuffix("px")))
        except ValueError:
            return None

    def _record_browser_signals(self) -> None:
        try:
            signals = self._do(lambda: self.driver.execute_async_script(BROWSER_SIGNALS_JS))
        except Exception as error:  # noqa: BLE001 - evidence gathering must not change the result
            signals = {"error": f"{type(error).__name__}: {str(error).splitlines()[0][:200]}"}
        self.ctx.event("browser_signals", signals if isinstance(signals, dict) else {})

    @staticmethod
    def _exchange_record(response: CapturedResponse) -> dict[str, Any]:
        """A decoded request and response. The `create` request holds the browser signals sent."""
        record: dict[str, Any] = {"http_status": response.status}
        for side, data, error in (
            ("request", response.request_body, response.request_body_error),
            ("response", response.body, response.body_error),
        ):
            if data is None:
                record[side] = None
                record[f"{side}_note"] = f"no body: {error}"
                continue
            try:
                record[side] = decode_body(data)
            except Exception as failure:  # noqa: BLE001 - a failed decode must not crash a run
                record[side] = None
                record[f"{side}_note"] = f"decode failed: {type(failure).__name__}"
                record[f"{side}_raw_length"] = len(data)
        return record

    def _classify_create(self) -> BotResult | None:
        if not self.creates and "create" in self.watcher.failed:
            return BotResult(
                Status.ERROR, "create_request_failed", "The create request failed before a response"
            )
        types = self._types()
        if "block" in types:
            return BotResult(Status.BLOCKED, "captcha_blocked")
        if not any(create["challenge_id"] for create in self.creates):
            return BotResult(Status.FAILED, "missing_challenge_id")
        latest = types[-1] if types else None
        if latest in CHALLENGE_TYPES:
            return BotResult(Status.BLOCKED, "challenge_unsolved")
        if latest not in ACCEPTED_TYPES:
            # Never guess: a type we have not seen cannot be treated as an accepted checkbox.
            return BotResult(Status.ERROR, "unknown_captcha_type", f"captcha_type={latest!r}")
        return None

    def _types(self) -> list[str]:
        """The types of the `create` answers we could decode. Only those decide the outcome."""
        return [c["captcha_type"] for c in self.creates if c["captcha_type"] is not None]

    def _widget_challenge_id(self) -> dict[str, Any]:
        return self._do(lambda: self.driver.execute_script(WIDGET_CHALLENGE_ID_JS)) or {}

    def _toast(self) -> dict[str, str] | None:
        try:
            toast = self.driver.find_element(By.CSS_SELECTOR, TOAST)
        except NoSuchElementException:
            return None
        classes = toast.get_attribute("class") or ""
        kind = (
            "success"
            if TOAST_SUCCESS in classes
            else "error"
            if TOAST_ERROR in classes
            else "other"
        )
        text = toast.text.strip()
        # The toast animates in, so its text can be empty for a moment. Wait for the message.
        return {"kind": kind, "text": text[:300]} if text else None

    @staticmethod
    def _json_body(response: CapturedResponse) -> Any:
        try:
            return json.loads(response.body.decode("utf-8")) if response.body else None
        except ValueError:
            return None

    @staticmethod
    def _body_text(response: CapturedResponse) -> Any:
        if response.body is None:
            return {"unreadable": response.body_error}
        parsed = Scenario._json_body(response)
        if parsed is not None:
            return parsed
        return response.body.decode("utf-8", errors="replace")[:500]

    def _screenshot(self, name: str) -> None:
        def capture() -> None:
            self.driver.execute_script(BLANK_PASSWORD_JS)
            self.ctx.artifact(f"{name}.png", "image/png", self.driver.get_screenshot_as_png())

        try:
            self._do(capture)
        except Exception as error:  # noqa: BLE001 - a missing screenshot must not change the result
            self.ctx.event("screenshot_failed", {"name": name, "type": type(error).__name__})
