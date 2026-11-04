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
