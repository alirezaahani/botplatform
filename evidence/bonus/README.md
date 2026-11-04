# Bonus: technical record of the experiments

Facts and numbers from the work on reducing CAPTCHA blocking, 2026-11-04. Branch `bonus/reduce-captcha-blocking`. Reasoning for the design choices is in `DECISIONS.md` (Bonus (a), (b), (c)); this file only records what was done and what was observed.

## Setup

| Item | Value |
|---|---|
| Target | `https://demo.arcaptcha.co/`, site key `d6ggpvy684` |
| Browser | Chrome for Testing 156.0.8078.80 and its matching chromedriver, in the worker image (Docker, amd64) |
| Driver | Selenium, `--no-sandbox`, performance log on (`goog:loggingPrefs`) |
| IP | One developer data center IP for every run. Manual Chrome on this IP always got the slider puzzle in earlier work. |
| Display (headful) | Xvfb `:99`, 1280x800x24, no window manager, noVNC for viewing |
| Credentials | `demo` / `demo` (public, shown on the demo page) |
| Total runs in the database | 79 (72 non-assisted: 4 + 16 + 1 live-viewer test + 21 + 10 + 10 + 10, plus 7 assisted) (start 09:30 UTC, last end 11:02 UTC) |
| `create` answers recorded | 80: 51 `block`, 29 `puzzle` (80 because one run had a second `create` after a rejected answer) |

## How the runs were made

- Each configuration is a browser `Profile` (`src/botplatform/profiles.py`) and a registered bot `arcaptcha-<profile>`. `arcaptcha` is the baseline.
- Run events stored for every ARCaptcha run: `browser_profile`, `browser_signals`, `create_request` (decoded request and response), `create_response`, `answer_request` (when an answer is sent), plus the original events. Nothing is redacted.
- Batches: `docker compose run --rm -T web python -m botplatform.batch --profiles <names> --modes <modes> --runs <n> --pause 5 --jitter 3 [--stop-after 0] --seed <s>`. Runs are shuffled, queued one at a time through the normal queue, and each is awaited before the next. The report is `/bonus` and `/bonus.md` (`?bot=`, `?since=`).
- A run took 12 to 23 seconds when blocked or at a puzzle (page load about 7 s, `create` answer about 2 s after the click, login about 1 s).

## Profiles

| Profile | Chrome arguments | Dropped switches | Start-up script |
|---|---|---|---|
| `baseline` | none | none | none |
| `stealth-flags` | `--disable-blink-features=AutomationControlled` | `enable-automation` | none |
| `no-cdc` | none | none | deletes `window` properties matching `/^\$?cdc_/` |
| `webgl-fix` | `--enable-unsafe-swiftshader` | none | none |
| `all-signals` | `stealth-flags` args + `webgl-fix` args | `enable-automation` | the `no-cdc` script |
| `all-signals-headless` | `all-signals` args + `--user-agent=<Chrome/156.0.0.0 string without Headless>` + `--window-size=1280,800` + `--screen-info={1280x800}` | `enable-automation` | the `no-cdc` script |

The start-up script runs through CDP `Page.addScriptToEvaluateOnNewDocument`. Base arguments from `chrome()` always apply first: `--no-sandbox`, `--headless=new` (headless) or `--window-size=1280,800 --window-position=0,0` (headful). Profile arguments come after them.

## What the browser sends (`create` request, `components.botD`)

Captured from the first live runs (`audit/baseline-and-stealth-flags.json`). The `create` body is plain JSON in the network event. Top-level keys: `CR` (value `FAKE_CR` in every run), `fp`, `lang`, `domain`, `site_key`, `bowman_id`, `components` (`botD`, `timeTaking`, `mouseTracker`, `fingerPrintComponents`), `system_time`, `last_seen_url`.

| `botD` field | baseline, headless | baseline, headful |
|---|---|---|
| `UserAgent` | `HeadlessChrome/156.0.0.0` | `Chrome/156.0.0.0` |
| `WindowAppVersion` | `5.0 (...) HeadlessChrome/156.0.0.0 ...` | `5.0 (...) Chrome/156.0.0.0 ...` |
| `WindowCDC.cdc_parameters` | 7 names `cdc_adoQpoasnfa76pfcZLmcfl_{Array,Object,Promise,Proxy,Symbol,JSON,Window}` | same 7 |
| `NavigatorWebdriver.is_webdriver` | true | true |
| `NavigatorWebdriver` patch fields | all false | all false |
| `VendorWebGL` | vendor `Google Inc. (Google)`, renderer `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)` | vendor `""`, renderer `""` |
| `WindowScreenSize` | screen 800x600, window 780x380 | screen 1280x800, window 1279x599 |
| `ChromeCsiApp` | `chrome_app` true, `chrome_csi` true | same |
| `WindowChromeObject` | `window_chrome_object` true, `is_web_view` false | same |
| `SecureChromeHeader` | false | false |
| `mouseTracker` | 1 click, `mouse_tracking` empty | same |

Other values from the same request: fonts `[]`, `fontPreferences` equal for `serif`, `apple` and `default`, timezone `UTC`, languages `["en-US"]`, `audioBaseLatency` -2, `screenFrame` `[0,0,0,0]`, hardware concurrency 8, device memory 16, headful `webGlBasics` and `webGlExtensions` `-1`.

`stealth-flags` changes `is_webdriver` to false in both modes (page `navigator.webdriver` false too) and removes the "controlled by automated test software" infobar (window height 437 vs 380 headless, 656 vs 599 headful). It leaves all 7 `cdc_` names.

## Measurements on the fake demo page (from `tests/test_profiles.py`)

| Setting | Headless baseline | Headless, `--user-agent` + `--window-size=1280,800` | Same + `--screen-info={1280x800}` | Headful |
|---|---|---|---|---|
| `navigator.userAgent` | `HeadlessChrome/156.0.0.0` | headful string | headful string | headful string |
| `navigator.appVersion` | `HeadlessChrome/156...` | `Chrome/156...` | `Chrome/156...` | `Chrome/156...` |
| `screen` | 800x600 | 800x600 | 1280x800 | 1280x800 |
| `window.inner` | 780x437 | 1280x657 | 1280x657 | 1279x656 |
| `window.outer` | 780x580 | 1280x800 | 1280x800 | 1279x799 |

- `cdc_` names are on `window` before page scripts run, are plain, writable and configurable, and stay deleted after reload and new navigation when the start-up script removes them.
- Headful baseline: `getContext('webgl')` is null. These alone each give SwiftShader vendor and renderer, identical to headless: `--enable-unsafe-swiftshader`, `--use-angle=swiftshader`, `--use-gl=angle --use-angle=swiftshader`. `--ignore-gpu-blocklist` gives Mesa llvmpipe. `--enable-webgl` and `--in-process-gpu` changed nothing.
- `--window-size` alone leaves the page's `screen` at 800x600 in headless. `--screen-info={1280x800}` changes it.
- `navigator.userAgentData.brands` is null on a non-secure page; the test checks it on the fake page and requires no brand containing "Headless".

## Experiments

"First `create` type" is the `captcha_type` of the first `create` response of each run. "Status" is the run's final status and reason. Every run recorded its own `challenge_id`.

| # | Configuration | Mode | Runs | First `create` type | Status | How it was run | Data |
|---|---|---|---|---|---|---|---|
| 1 | `baseline`, `stealth-flags` | headless and headful, 1 each (09:30 to 09:31 UTC) | 4 | `block` ×4 | `blocked/captcha_blocked` | by hand through `POST /bots/<id>/runs` | `audit/` |
| 2 | baseline and the 3 single-factor profiles | both | 16 | `block` ×16 | `blocked/captcha_blocked` | batch, `--runs 2 --seed 1` | database; `results-ip1-datacenter.md` |
| 3 | matrix of 6 profiles (the 100 planned runs were cut by the early stop and by hand) | both | 21 (10:04 to 10:11 UTC) | `block` ×20, `puzzle` ×1 | 20 `blocked/captcha_blocked`, 1 `blocked/challenge_unsolved` (the one `puzzle` was `all-signals`, headful) | batch, `--runs 10 --seed 2`, stopped by hand while one run was still active | `results-ip1-datacenter.md` |
| 4 | `all-signals` | headful | 10 | `puzzle` ×10 | `blocked/challenge_unsolved` | batch, `--stop-after 0 --seed 3` | `results-ip1-all-signals-repeat.md` |
| 5 | `all-signals` | headless | 10 | `block` ×10 | `blocked/captcha_blocked` | batch, `--stop-after 0 --seed 4` | `results-ip1-all-signals-headless.md` |
| 6 | `all-signals-headless` | headless | 10 | `puzzle` ×10 | `blocked/challenge_unsolved` | batch, `--stop-after 0 --seed 5` | `results-ip1-all-signals-headless-profile.md` |
| 7 | `arcaptcha-assisted` (`all-signals`, a person solves) | headful | 7 | `puzzle` ×7 | `success/human_solved` ×7 | by hand, one at a time | `assisted/` |

First `create` type per bot and mode over all 79 runs (one row each, includes the one run used to test the live viewer, which the report excludes from rates):

| Bot | Mode | `block` | `puzzle` |
|---|---|---|---|
| `arcaptcha` (baseline) | headful | 7 | 0 |
| `arcaptcha` (baseline) | headless | 8 | 0 |
| `arcaptcha-stealth-flags` | headful | 3 | 0 |
| `arcaptcha-stealth-flags` | headless | 4 | 0 |
| `arcaptcha-no-cdc` | headful | 2 | 0 |
| `arcaptcha-no-cdc` | headless | 5 | 0 |
| `arcaptcha-webgl-fix` | headful | 7 | 0 |
| `arcaptcha-webgl-fix` | headless | 4 | 0 |
| `arcaptcha-all-signals` | headful | 0 | 11 |
| `arcaptcha-all-signals` | headless | 11 | 0 |
| `arcaptcha-all-signals-headless` | headless | 0 | 10 |
| `arcaptcha-assisted` | headful | 0 | 7 |

What each profile sent in the live runs (from the decoded `create` requests of experiment 2, same on repeat):

| Profile | `cdc_` names | `is_webdriver` | WebGL renderer, headful |
|---|---|---|---|
| baseline | 7 | true | empty |
| `stealth-flags` | 7 | false | empty |
| `no-cdc` | 0 | true | empty |
| `webgl-fix` | 7 | true | SwiftShader |
| `all-signals-headless` (headless) | 0 | false | SwiftShader; UA `Chrome/156.0.0.0`, screen and window 1280x800 (window 657 high) |

## The slider answer (assisted runs)

Seven runs, a person using a real mouse through noVNC; the person described how they moved.

- `create` response when a puzzle is chosen: `{"status": "OK", "content": {"y": 70, "site_key", "challenge_id", "puzzle_piece": "gAAAAA...", "puzzle_background": "gAAAAA..."}, "captcha_type": "puzzle"}`. `y` was 70 in the logged run. The two image fields are long strings starting `gAAAAA`.
- `answer` request: `{"answers": <int>, "site_key": "d6ggpvy684", "drag_drop": 0, "challenge_id": "<the id from create>", "drag_drop_time": <ms timestamp>}`. Observed `answers`: 150, 92, 142, 155, 173, 140, 168 (rejected), 178. `drag_drop` was 0 in all. `drag_drop_time` is a Unix timestamp in milliseconds (consecutive runs differ by the time between them).
- `answer` response: HTTP 200 with `{"success": true}` or `{"success": false}`.
- After `success: false` (run 6, `answers` 168): a new `create` (HTTP 201, type `puzzle`, new `challenge_id`) came back within about 0.5 s. The next `answer` (178) was `success: true`, and the login succeeded with the second `challenge_id`.
- After `success: true`: no new `create`; the bot logs in 3 s later. Login returned HTTP 200 `{"msg": "You are logged in successfully!"}` with a green toast, in all 7 runs.

| Run | Movement (person's words) | Puzzle shown to answer | `answers` | `answer` | Run seconds |
|---|---|---|---|---|---|
| 1 | natural | about 12 s | 150 | true | 32.0 |
| 2 | natural | about 11 s | 92 | true | 26.6 |
| 3 | wiggle | about 16 s | 142 | true | 31.4 |
| 4 | fast, not straight | about 5 s | 155 | true | 27.1 |
| 4b | fast, not straight | about 2.4 s | 173 | true | 18.8 |
| 5 | slow | about 38 s | 140 | true | 52.9 |
| 6 | wrong, then correct | about 25 s, then about 7 s | 168, 178 | false, true | 50.0 |

Run ID, event timeline and raw bodies are in `assisted/runs.json`.

## Statuses seen

| Status / reason | Meaning here | Where seen |
|---|---|---|
| `blocked/captcha_blocked` | the `create` answer was `block` | experiments 1 to 3 and 5 |
| `blocked/challenge_unsolved` | the `create` answer was `puzzle` and nothing solved it | experiments 3, 4 and 6 |
| `success/human_solved` | a person solved the puzzle and the login was verified | experiment 7 |

After a block, `POST /api/login` returned HTTP 400 `{"msg":"Please solve captcha"}` (earlier work, DECISIONS.md step 2). After a puzzle that nothing solved, the login step failed with `ElementNotInteractableException` because the popup covers the form.

## Not measured

- Whether the site would accept an answer made by Selenium (the assisted runs used a real mouse).
- Whether a straight drag is accepted: neither attempt by the person was straight.
- The request to `lab.arcaptcha.co/mouse/api/store` (mouse history and verdict) is not captured.
- Which of the two `all-signals-headless` additions (user agent or screen size) is needed, and which of the three `all-signals` changes is needed together with the others. No leave-one-out profile was run.
- Runs on any IP other than this one, at other times of day, or with other Chrome versions or Chrome stable.
- The meaning of `drag_drop`, and what the `CR` field is for.
- Experiments 4 to 6 were run in blocks and not interleaved with other profiles; experiments 2 and 3 were interleaved.

## Files

| Path | Contents |
|---|---|
| `audit/README.md`, `audit/baseline-and-stealth-flags.json` | the first four live runs, the signal table, and the notes on what the container shows |
| `results-ip1-datacenter.md` | `/bonus.md` export after experiments 2 and 3, with notes |
| `results-ip1-all-signals-repeat.md` | experiment 4 |
| `results-ip1-all-signals-headless.md` | experiment 5 |
| `results-ip1-all-signals-headless-profile.md` | experiment 6 |
| `assisted/README.md`, `assisted/runs.json` | experiment 7 |
