# Phase A: signal audit

Four live runs on 2026-11-04 from the project's Docker stack on the developer's own IP (the same IP used for every run so far): `arcaptcha` and `arcaptcha-stealth-flags`, each in `headless` and `headful`. Raw data (run rows, `browser_profile`, `browser_signals`, `create_request`, `create_response` events) is in `baseline-and-stealth-flags.json`.

**All four runs ended `blocked` / `captcha_blocked`, and each recorded a `challenge_id`.** Four runs say nothing about rates. They show what the browser sends, which is the point of this phase.

## Checks that were open

| Question | Result |
|---|---|
| Does the real `create` request body reach the run's record? | Yes, all four runs. It is plain JSON in the network event, so the `getRequestPostData` fallback was not needed. |
| Does `stealth-flags` change `navigator.webdriver`? | Yes. `true` in both baseline runs, `false` in both `stealth-flags` runs, and the server-side `botD.NavigatorWebdriver.is_webdriver` agrees. The detector's patch checks (`is_prototype_string_patch`, `is_navigator_object_patched`) stay `false`, so the flag approach is not seen as a patch. |
| Are the captured values sensible? | Yes, see below. Two findings (headful WebGL, empty mouse track) were not expected. |

## What the server receives (`create` request, `components.botD`)

| Signal | baseline / stealth-flags, headless | baseline / stealth-flags, headful |
|---|---|---|
| `NavigatorWebdriver.is_webdriver` | true / **false** | true / **false** |
| `WindowCDC.cdc_parameters` | 7 `cdc_adoQpoasnfa76pfcZLmcfl_*` names, both profiles | same |
| `UserAgent` | `HeadlessChrome/156.0.0.0` | `Chrome/156.0.0.0` |
| `VendorWebGL` | Google Inc. / ANGLE SwiftShader (software) | **empty vendor and renderer** (`navigator` page check: no WebGL context) |
| `WindowScreenSize` | screen 800x600, window 780x380 (baseline) or 780x437 (stealth) | screen 1280x800, window 1279x599 (baseline) or 1279x656 (stealth) |
| `ChromeCsiApp`, `WindowChromeObject` | present | present |
| `mouseTracker.mouse_tracking` | **empty** (1 click, no movement) | **empty** |

## Suspects, in the order I would test them

1. **`cdc_` properties.** Still present in every run, including `stealth-flags`. The flags do not remove them, so a profile has to.
2. **No WebGL in headful mode.** The Xvfb display gives no WebGL context, and a real desktop Chrome always has one. Headless uses SwiftShader, which is also a software renderer.
3. **No mouse movement before the click.** `element.click()` dispatches the click without moving the pointer, so the mouse SDK has nothing to look at. This is Phase C.
4. **`HeadlessChrome` in the user agent, and the 800x600 headless screen.** Both are easy to change.
5. **Chrome for Testing itself,** and the performance log we use to read responses. Both are unchanged so far.

## Notes

- `stealth-flags` also removes Chrome's "controlled by automated test software" infobar, which is why its window is taller (437 vs 380 headless, 656 vs 599 headful).
- The request has a field `CR` with the value `FAKE_CR` in every run. We do not know what the site does with it.
- The flags the profiles use are in `src/botplatform/bots/profiles.py`, with the reason for each in its description.

## Environment leaks from Docker, and limits we imposed

The `fingerPrintComponents` in the same `create` request (identical in the baseline runs, apart from the WebGL items) show what the container reveals. These are observations from the four runs, not proof that the server uses any of them.

| Item | What the container shows | Why it may stand out |
|---|---|---|
| Installed fonts | `fonts: []`, and `fontPreferences` gives the same width for `serif`, `apple` and `default` | The image has almost no fonts, so every generic family falls back to one face. A desktop browser has dozens. |
| WebGL | headless: SwiftShader (software); headful: none (`webGlBasics: -1`, `webGlExtensions: -1`) | No GPU in the container. |
| Time zone and language | `UTC`, `en-US` only | A container default, and unusual for a real user (the demo is an Iranian site). Not tested yet. |
| Audio | `audioBaseLatency: -2` | No audio device. |
| Screen | `screenFrame: [0,0,0,0]` (no taskbar or menu bar), headless 800x600, headful fixed 1280x800 | Real desktops have a larger screen and a non-zero frame. |
| CPU and memory | 8 cores, 16 GB | These are the host's values, because the container is not limited. They look normal. |
| TLS (JA4) and IP | Sent from the host's network stack and IP | Docker does not change either, and manual Chrome got a puzzle from the same IP, so the IP and TLS from this machine are unlikely to be the cause. |

What Docker does not leak to the page: `/.dockerenv`, cgroups and the hostname are not reachable from page JavaScript. The container only affects what the browser itself can see, which is the table above.

**Limits we set that may constrain bot development later:**

- The headful screen is fixed at 1280x800 by `worker/start.sh` (Xvfb) and by the base Chrome arguments. A profile can change the window size, because its arguments come last, but not the screen itself.
- Chrome for Testing is pinned to one version (DECISIONS.md 1a), so we have not compared it with Chrome stable.
- We read network responses through Chrome's performance log, so a profile that turns the log off has no way to read `create`. Such a profile would need another capture method.

Fonts, time zone, language and screen are candidates for later profiles if the first matrix shows that `cdc_` and WebGL are not enough.
