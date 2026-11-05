# Bot platform

A small platform that runs bots and records every run. A web UI launches a run, a worker executes it (a real Chrome for browser bots), and Postgres holds the queue, the status, the timeline and the screenshots. It ships with a trivial `example` bot, an ARCaptcha demo-site bot, variants of that bot used for the bonus work (see [Reducing CAPTCHA blocking](#reducing-captcha-blocking-bonus)), and four solver bots that solve the slider puzzle by themselves (see [Solving the slider](#solving-the-slider-the-solver-bots)).

```
browser --> web --> Postgres <-- worker(s)
                                 Chrome + Xvfb + noVNC (live view, proxied by web)
```

## Requirements

- Docker Engine with the Compose plugin, on Linux with an amd64 CPU. This is what was tested: development on an Ubuntu-like Linux host, and CI on GitHub's `ubuntu-latest` runner.
- Docker Desktop on macOS or Windows with an amd64 CPU is untested. It may work, but nothing in this repo checks it.
- ARM64 is a limitation: it is not supported and has not been tried.
- Internet access. The image build downloads Chrome for Testing, and the `arcaptcha` bot reaches the ARCaptcha demo site at run time.
- Each worker container asks for 1 GB of shared memory (`shm_size` in `compose.yaml`) for Chrome. Other disk and RAM needs were not measured.

## Quick start

```
cp .env.example .env        # then change POSTGRES_PASSWORD (letters and numbers only)
docker compose up --build
```

Open http://127.0.0.1:8000, pick a bot on `/bots` and press launch. The first build downloads Chrome for Testing and takes a few minutes.

## Configuration

Settings are environment variables in `.env` (copy `.env.example`). `compose.yaml` reads them and passes each to the container that needs it. Credentials stay in `.env`, outside the source code, and `.env` is not committed.

| Variable | Default in `.env.example` | Meaning |
|---|---|---|
| `POSTGRES_USER` | `botplatform` | Database user. |
| `POSTGRES_PASSWORD` | `change-me` | Database password. Change it. Use letters and numbers only, because it is placed in a connection URL. |
| `POSTGRES_DB` | `botplatform` | Database name. |
| `WEB_PORT` | `8000` | Port the web UI is published on, on 127.0.0.1 only. |
| `RUN_TIME_LIMIT_SECONDS` | `180` | A run is killed and marked `timeout` after this many seconds. |
| `ARCAPTCHA_USERNAME` | `demo` | Login name the ARCaptcha bots use. The demo site shows these credentials on its login page. |
| `ARCAPTCHA_PASSWORD` | `demo` | Login password the ARCaptcha bots use. |

The three `POSTGRES_*`, `ARCAPTCHA_USERNAME` and `ARCAPTCHA_PASSWORD` must be set (`compose.yaml` refuses to start without them). `WEB_PORT` and `RUN_TIME_LIMIT_SECONDS` fall back to 8000 and 180 if unset. `compose.yaml` also accepts `LEASE_SECONDS` (30) and `LEASE_RENEW_SECONDS` (5) for the worker's run lease; they are not in `.env.example` and rarely need changing.

## Using it

- `/bots`: the registered bots and their modes, with a launch button for each. The newest bot is first. The list has the baseline `arcaptcha`, one `arcaptcha-<profile>` bot per browser profile, the four `arcaptcha-solver-*` bots, and the `example` bot.
- `/stats`: one row per bot and mode with the number of finished runs, how many ended in each status, and the success rate with a 95% Wilson interval. Only finished runs count. Runs where someone opened the live viewer may have been helped by a person, so they are left out of the counts and the rate and shown only in the Watched column. Success means the status `success`, which for the ARCaptcha bots is a verified login.
- `/runs`: the run history, newest first, with the queued, started and ended times (UTC) and the duration. Started, ended and duration are blank while a run has not started or finished.
- `/runs/{id}`: status, reason, `challenge_id`, the timeline and screenshots. The page refreshes while the run is active.
- The `example` bot (mode `direct`) uses no browser, adds one timeline event and succeeds. It checks the platform itself.
- The `arcaptcha` bot opens the ARCaptcha demo login page, records the `challenge_id` from the `create` response, then logs in with the demo credentials and checks the result. Modes: `headless` (no window) or `headful` (visible in the live view).

### Run statuses

| Status | Meaning |
|---|---|
| `queued`, `running` | Waiting for a worker, or in progress. |
| `success` | The bot completed its scenario. |
| `blocked` | The site refused or demanded a puzzle (`captcha_blocked`, `challenge_unsolved`). |
| `failed` | The bot ran but the outcome was wrong (for example `verification_failed`). |
| `timeout` | A step or the whole run exceeded its time. |
| `error` | A platform or bot crash. |

A bot adds a short reason code to each status. See [DECISIONS.md, 3a](DECISIONS.md) for the full table.

A `blocked` run counts as a failed run, even when its `challenge_id` was recorded, because the scenario also includes logging in and checking the result. The run stays in the history with its `challenge_id`. This is our own reading of the task and has **not** been confirmed with ARCaptcha.

### Watching a run live

Launch an ARCaptcha run in `headful` mode. While it is queued or running, its page shows a "Watch live" link that opens the worker's browser in noVNC. You can use the mouse and keyboard. This was checked by hand in a real browser: the mouse and keyboard work.

The browser runs inside the worker container, on a virtual display. It is not a window on your desktop. The web container proxies the view, so you only need the web port.

If anyone opens the live view, the run page warns that the result may be human-assisted.

**Desktop** (Docker runs on the machine you are using): open `http://127.0.0.1:8000/runs/<id>` and click "Watch live".

**Server** (Docker runs on another machine): the port only listens on the server's `127.0.0.1`. Open a tunnel from your own machine, then use the same address in your browser:

```
ssh -L 8000:127.0.0.1:8000 user@server
```

To check that the worker image brings up the display and viewer, run `tests/core/check_viewer.sh`.

## Reducing CAPTCHA blocking (bonus)

The approach: the site blocks the plain bot at the first `create` request, so the bot can take a different browser profile (`src/botplatform/bots/utils/profiles.py`): Chrome arguments, dropped Selenium switches and a start-up script that hides automation signals. Each profile is its own registered bot, `arcaptcha-<profile>`, so every run lands in the normal run history, and the history is the evidence. `all-signals` combines the three single-factor profiles and is meant for `headful`. `all-signals-headless` adds a normal user agent and screen size, and is meant for `headless`.

Live results, first `create` answer of each run (one IP, 2026-11-04, from [evidence/bonus/README.md](evidence/bonus/README.md)):

| Bot | Mode | First `create` answer |
|---|---|---|
| `arcaptcha` (baseline) | headful and headless | `block` in 15 of 15 runs (7 headful, 8 headless) |
| `arcaptcha-stealth-flags`, `-no-cdc`, `-webgl-fix` | both | `block` in every run |
| `arcaptcha-all-signals` | headful | `puzzle` in 11 of 11 runs |
| `arcaptcha-all-signals-headless` | headless | `puzzle` in 10 of 10 runs |

Limits, stated plainly:

- One IP, one day and small counts. The repeat batches were run in blocks and not interleaved with other profiles. Results depend on the IP and the day, and may differ for you.
- These profile bots do not solve the slider. A run of one of them that gets a puzzle still ends `blocked` with reason `challenge_unsolved`, never `success`. The profiles reduce blocking; the solver bots (below) are what solve the puzzle.
- A `blocked` or unsolved run is a failed run in the history. The success counts for the solver bots are in the next sections; none is claimed for the profile bots.

### Reproducing the measurement

```
# a solver bot, both modes, 10 runs each
docker compose run --rm -T web python -m botplatform.batch --bots arcaptcha-solver-halo-linear --runs 10 --pause 10

# a profile bot, headful only
docker compose run --rm -T web python -m botplatform.batch --bots arcaptcha-all-signals --modes headful --runs 10
```

The worker must be running. The batch queues the runs one at a time through the normal queue, waits for each, and prints one line per run (`number/total bot mode status reason challenge_id seconds`). The results are on `/stats`. It talks to the live demo site, so it is not part of the tests.

| Option | Default | Meaning |
|---|---|---|
| `--bots` | required | Comma separated bot ids, as listed on `/bots`. |
| `--modes` | `headless,headful` | Comma separated modes. Every bot must support every mode given (exit code 2 otherwise). A bot with its own modes needs them named, for example `--bots example --modes direct`. |
| `--runs` | 10 | Runs per bot and mode. |
| `--pause` | 10 | Seconds between runs. |

The runs of all bots and modes are shuffled together.

Then open `/stats`: every batch run is a normal run, so it is counted there with the rest of the history.

## Solving the slider (the solver bots)

Four automatic bots, in `headful` or `headless` mode (headful uses the `all-signals` browser profile, headless the `all-signals-headless` one). Each is a pair of a gap finder and a movement shape:

| Bot | Finds the gap with | Moves the handle |
|---|---|---|
| `arcaptcha-solver-halo-linear` | `halo`: detects the light halo around the gap and measures its body square | 8 equal steps, about 0.6 s |
| `arcaptcha-solver-halo-eased` | `halo` | ease-out over 25 to 40 steps, 0.8 to 1.5 s, 1 to 2 px vertical wobble |
| `arcaptcha-solver-silhouette-linear` | `silhouette`: slides the piece's own outline along its row and scores the fit | 8 equal steps |
| `arcaptcha-solver-silhouette-eased` | `silhouette` | ease-out, as above |

**How a run goes.** The bot ticks the checkbox like the others. If the site shows a puzzle, the bot fetches both images inside the page (the piece and the background, in memory), asks the finder for the answer, and drags the slider handle there with Selenium in one press, one smooth motion and one release. The site judges the answer, then the platform logs in and verifies the result like for any bot. The bot makes up to 3 answers: a wrong one brings a new puzzle at once.

**What the site wants, as measured on the live page.** The background is 260x160 px and the piece a separate 50x50 PNG with its outline in the alpha channel. The handle and the piece move together 1:1 along x, stop at 196 px, and the answer sent is that position. The right answer is the gap's left edge minus 10 px. Drags that landed exactly there were accepted; drags 10 px or more away were rejected; people were accepted up to 4 px away. The evidence is in [evidence/solver/](evidence/solver/README.md).

**Results**

| Reason | Status | Meaning |
|---|---|---|
| `solved` | `success` | The answer was accepted and the login was verified. |
| `solve_failed` | `blocked` | 3 answers in a row were rejected. |
| `gap_not_found` | `blocked` | The finder found no gap, so the bot made no drag and did not guess. |
| `puzzle_ready` | `timeout` | The puzzle's images did not load in time. |

Live results, one IP, 2026-11-04: each of the four bots was run 10 times in each mode, interleaved, 15 seconds apart. All 80 runs (40 headful, 40 headless) ended `success` / `solved`, all on the first attempt, with a median run of about 15 to 16 s. Tables and per-run rows: [headful](evidence/solver/results-headful-2x2.md) and [headless](evidence/solver/results-headless-2x2.md).

Limits, stated plainly:

- 80 of 80 does not mean a 100% success rate: with no failures it only says the failure rate is probably below about 4% over all runs (about 7% per mode). It also does not separate the four bots; neither the finder nor the movement shape changed whether the site accepted the answer.
- One IP and one evening for both modes. Another network or time of day may differ, and a site that scores movement could change without notice.
- The 80-run comparison was driven by a small shell loop that posts to `/bots/<bot id>/runs` with `mode=headful` or `mode=headless` and waits for each run. It can now be repeated with the batch runner above, which has not been done.
- The solver needs OpenCV, which is installed in the worker image only (the `solver` extra in `pyproject.toml`).

To run one: pick a `arcaptcha-solver-*` bot on `/bots` and press launch. Open the run page to see the timeline: `solve_attempt` holds the finder's answer, the drag and where the handle ended (how to read it: [evidence/solver/README.md](evidence/solver/README.md)). Design reasons: [DECISIONS.md](DECISIONS.md), the solver sections of step 8.

## Scaling

```
docker compose up -d --scale worker=3
```

Each worker runs one bot at a time and claims runs from the database queue, so no two workers take the same run. A worker holds a lease on its run and renews it. If a worker dies, its run is reaped and marked `error` (`worker_lost`). A run is stopped and marked `timeout` after `RUN_TIME_LIMIT_SECONDS` (180 by default, set in `.env`).

## Tests

```
docker compose -f compose.test.yaml run --rm --build tests
```

It runs the Chrome tests on four parallel workers and then the database tests one after the other (they share one database). This needs only Docker and no `.env`. It uses its own project name and a throwaway Postgres, so it never touches the main stack. The bot tests run real Chrome against a fake ARCaptcha demo page served by pytest. The fake can return any outcome on demand (a block, a puzzle, a hang, a dropped connection), so every failure path is repeatable without the live site.

To check the fake against the real site, run the live test (needs internet):

```
docker compose -f compose.test.yaml run --rm --build tests pytest -m live -v -s
```

Lint, format and type checks (they need `uv sync --all-extras`, so that pyright can resolve OpenCV, numpy, Selenium and FastAPI):

```
uv run ruff check src tests migrations
uv run ruff format --check src tests migrations
uv run pyright
```

CI (`.github/workflows/ci.yml`) runs these checks and the tests, then starts the stack and launches a run of each bot. You can run that check locally with `.github/scripts/smoke.sh`.

Real output of the test command:

```
64 passed in 45.94s      (Chrome tests, 4 workers)
157 passed, 65 deselected in 16.41s    (everything else)
(the live test is never run by this command)
```

### What the tests cover

The tests mirror the code. `tests/core/` covers the platform (queue, worker, viewer, stats, migrations). `tests/bots/utils/` covers the Selenium helpers against a plain local page and imports nothing from ARCaptcha. `tests/bots/arcaptcha/` covers the ARCaptcha bots against the fake demo page in `tests/bots/arcaptcha/fake_demo/`; the full-run cases are in `test_run.py`; the decisions behind them (which `create` answers block, which login responses count) are in `test_checkbox.py` and `test_login.py` and need no Chrome. `tests/bots/test_registry.py` holds the registry snapshot and its wiring. The bonus and stats work add rows at the end of the table. Each row lists the status and reason that the test asserts.

| Case | Test | Result |
|---|---|---|
| Main success workflow | `test_an_accepted_checkbox_then_a_confirmed_login_succeeds` (types `accept` and `cookie`), `test_a_softban_is_judged_by_the_login_alone` | `success` |
| Missing `challenge_id` | `test_what_the_create_answers_say_about_the_run` (`tests/bots/arcaptcha/test_checkbox.py`), `test_a_create_body_nobody_can_decode_fails_without_crashing` | `failed`, `missing_challenge_id` |
| CAPTCHA blocking | `test_a_block_still_logs_in_and_a_good_login_never_upgrades_it` | `blocked`, `captcha_blocked` |
| Puzzle or unsolved challenge | `test_a_puzzle_no_one_solves_ends_blocked_but_still_tries_the_login`, and the `puzzle`, `question` and `2fa` cases in `tests/bots/arcaptcha/test_checkbox.py` | `blocked`, `challenge_unsolved` |
| Step timeouts | `test_a_step_that_never_finishes_times_out_with_its_name` in `tests/bots/arcaptcha/test_run.py` (page, checkbox, create, login) | `timeout`, reason is the step: `load_page`, `find_checkbox`, `create_response`, `login_response` |
| Whole-run timeout | `test_a_hung_child_and_its_grandchild_are_killed_at_the_time_limit` in `tests/core/test_worker.py` | `timeout`, `run_time_limit` |
| Unsuccessful form verification | `test_a_login_the_page_does_not_confirm_fails_verification`, and `test_a_login_counts_only_when_the_response_and_the_toast_agree` in `tests/bots/arcaptcha/test_login.py` | `failed`, `verification_failed` |
| Dropped connections | `test_a_failed_create_request_is_an_error_straight_away`, `test_a_dropped_login_is_an_error_unless_the_run_already_failed` | `error`, `create_request_failed` or `login_request_failed` |
| Dropped login after a block | `test_a_dropped_login_is_an_error_unless_the_run_already_failed` (after a block), `test_a_blocked_run_whose_login_hangs_stays_blocked` | `blocked`, `captcha_blocked` |
| Queue claim | `test_claim_is_fifo`, `test_claim_marks_the_run_running_with_a_lease`, `test_concurrent_claims_never_duplicate_or_lose_a_run` in `tests/core/test_queue.py` | one claim per run |
| Leases and reaping | `test_renew_extends_the_lease`, `test_reap_expired_marks_only_expired_running_runs`, `test_a_late_finish_after_reaping_changes_nothing` in `tests/core/test_queue.py`; `test_the_lease_is_renewed_while_the_child_runs`, `test_losing_the_lease_kills_the_child_and_keeps_the_reapers_status` in `tests/core/test_worker.py` | `error`, `worker_lost` |
| Worker crash and stop | `test_a_child_that_exits_without_a_result_is_bot_process_died`, `test_sigterm_kills_the_child_and_marks_the_run_worker_stopped` in `tests/core/test_worker.py` | `error`, `bot_process_died` or `worker_stopped` |
| Viewer proxy | `test_live_redirects_to_novnc_through_the_proxy`, `test_websocket_carries_bytes_both_ways`, `test_websocket_closes_when_the_run_ends`, `test_proxy_refuses_runs_that_cannot_be_watched`, `test_watch_live_link_rules` in `tests/core/test_viewer.py` | proxy and link rules |
| Browser profiles | `tests/bots/utils/test_profiles.py` (10 tests): each profile changes what the page sees (`navigator.webdriver`, `cdc_` names, WebGL, user agent, screen size) and not before page scripts; `tests/bots/arcaptcha/test_run.py` records the profile, the browser signals and the decoded `create` request | profile rules |
| Registry | `tests/bots/test_registry.py` (2 tests): a snapshot of the registry's ids, names and modes in order (a repeated id would collapse in the dict and break it), and every profile has a registered bot that runs with it; `tests/core/test_registry.py` (1 test): a bot removed from the published list is marked inactive and kept | registry rules |
| Selenium helpers | `tests/bots/utils/test_browser.py` (12 tests): `do`, `wait_for` and `StepTimeout`, and `SeleniumBot` (picks the profile by mode, records `browser_profile`, turns a timeout into `timeout` with a screenshot, screenshots and re-raises any other error); `test_network.py` (12 tests): `ResponseWatcher` and its records; `test_page_scripts.py` (6 tests): browser signals and in-page fetches | helper behaviour |
| Drag | `tests/bots/utils/test_drag.py` (17 tests): both paths end exactly on the target, durations and wobble stay in bounds with a seeded generator, edge cases of 0 and 196 px, and a real drag on a local page | path shape |
| Stats | `tests/core/test_stats.py` (14 tests): the 95% Wilson interval (0 of n, n of n), and the page: counts per bot and mode, the rate and interval text, 80 of 80 not shown as a certain 100%, watched runs left out but counted, queued and running runs not counted, runs of an inactive bot still shown, an empty history, and the `/runs` started, ended and duration columns | interval values, counts, rate and columns |
| Migrations | `tests/core/test_migrations.py` (1 test): `alembic upgrade head` and `alembic check` in a database of its own, so the migration matches the models | no drift |
| Puzzle capture | `tests/bots/arcaptcha/test_puzzle_capture.py` (3 tests): a puzzle is saved as two artifacts and an event, images without a content type are saved as `.bin`, broken images record a failure and leave the result unchanged | artifacts and `puzzle_captured` events |
| Gap finders | `tests/bots/arcaptcha/test_gap_finders.py` (37 tests): both finders (`halo` and silhouette) return the expected target on 8 real puzzles (stored in `tests/bots/arcaptcha/fixtures/`) and raise `GapNotFound` on blank or garbage input; the silhouette finder is also tested with noise, a piece without alpha and a row outside the image | the answer in px, or `GapNotFound` |
| Solver bots | `tests/bots/arcaptcha/test_slider_solver.py` (11 tests): solver bots solve a real fixture puzzle on the fake page, each solver bot is registered and picks its profile by mode, a wrong first target is rejected and then solved, all attempts rejected ends `blocked`, no gap ends `blocked` without a drag, a handle that ignores the first press is pressed again without counting as an attempt | `success`, `solved` and the failure cases |

## Adding a bot

A bot is an instance of a `Bot` subclass that implements the contract in `src/botplatform/contract.py`:

```python
from enum import StrEnum

from botplatform.contract import Bot, BotResult, RunContext, Status


class HelloMode(StrEnum):
    DIRECT = "direct"


class HelloBot(Bot[HelloMode]):
    def __init__(self) -> None:
        super().__init__(
            id="hello",
            name="Hello bot",
            description="Adds one event and succeeds.",
            modes=HelloMode,
        )

    def run(self, ctx: RunContext, mode: HelloMode) -> BotResult:
        ctx.event("hello", {"mode": mode})
        return BotResult(status=Status.SUCCESS)  # or e.g. Status.FAILED, reason="my_reason"
```

Then register it in the explicit dict in `src/botplatform/bots/__init__.py`. Append new bots at the **end** of `BOTS`: the insertion order is the order bots were added, and the UI shows the newest (last) first.

```python
BOTS: dict[str, Bot[Any]] = {bot.id: bot for bot in [ExampleBot(), BASELINE_BOT, ..., HelloBot()]}
```

A browser variant of the ARCaptcha bot needs no new class: it is one entry in `PROFILES` in `src/botplatform/bots/utils/profiles.py`, which registers a bot `arcaptcha-<name>`.

A bot that drives Chrome can subclass `SeleniumBot` and implement only `steps(browser)`:

```python
from botplatform.bots.utils.browser import BrowserSession, SeleniumBot, wait_for
from botplatform.contract import BotResult, Status


class TitleBot(SeleniumBot):
    def __init__(self) -> None:
        super().__init__(id="title", name="Title bot")

    def steps(self, browser: BrowserSession) -> BotResult:
        browser.driver.get("https://example.com")
        wait_for(browser, lambda: browser.driver.title, seconds=10, step="load_page")
        return BotResult(status=Status.SUCCESS)
```

`SeleniumBot` gives the bot a browser profile per mode (`profile` and `profile_by_mode`), the `browser_profile` event, a `timeout` result when a step raises `StepTimeout` (as `wait_for` does), and an `error` screenshot when anything else is raised. Its modes are the `BrowserMode` enum (`headless`, `headful`), and only headful runs can be watched live.

The bot `id` must be unique: a repeated id silently replaces the earlier bot in the dict, and the registry snapshot test (`tests/bots/test_registry.py`) is what catches it, so add the new bot to that snapshot too. The worker publishes the list at startup, so the new bot appears on `/bots` after you restart the worker (`docker compose up -d --build worker`). `ctx` also offers `event()`, `record_challenge_id()` and `artifact()`. An uncaught exception is recorded as `error`.

You can use another automation engine, such as Playwright, in the same way. The contract only needs `run(ctx, mode) -> BotResult`, and the core never imports Selenium. The optional Selenium helpers live in `src/botplatform/bots/utils/`: `browser.py` (the `chrome()` launcher, `SeleniumBot`, `wait_for`, the alert-aware `do`, `screenshot`), `profiles.py` (browser profiles), `network.py` (`ResponseWatcher`), `drag.py` (drag paths and `perform_drag`) and `page_scripts.py` (browser signals and in-page fetches). A bot with another engine would start its own browser, and send screenshots with `ctx.artifact(name, "image/png", data)` and timeline entries with `ctx.event()`. Nothing in this repo has a Playwright bot, and Playwright is not a dependency. Its browser would also have to be installed in the worker image.

## Data persistence

The run history lives in Postgres, on the named volume `postgres-data` (see `compose.yaml`). It survives `docker compose down`, a restart and a rebuild. Only `docker compose down -v` deletes it.

To check it:

1. Launch the `example` bot on `/bots`, and see the run on `/runs`.
2. Run `docker compose restart` (or `docker compose down` and then `docker compose up -d`).
3. Open `/runs` again. The run is still there.

## Stop and reset

```
docker compose down       # stops everything, keeps the run history
docker compose down -v    # also deletes the database volume
```

## Troubleshooting

- `permission denied` from Docker: add your user to the `docker` group (`sudo usermod -aG docker $USER`), then log in again.
- Port 8000 is in use: set `WEB_PORT` in `.env`.
- The first build is slow: it downloads Chrome for Testing. Later builds reuse the cached layers.
- `set it in .env` from Compose: `.env` is missing or a required value is empty. Run `cp .env.example .env`.
- A password with special characters breaks the database connection: it is placed in a connection URL. Use letters and numbers only, then run `docker compose down -v` once, because Postgres keeps the password it first started with.
- A run ends `blocked`: the site refused the bot or showed a puzzle (`captcha_blocked`, `challenge_unsolved`). This is a recorded result, not a bug. The `challenge_id` is kept on the run page. For a solver bot the reasons are `solve_failed` (3 answers rejected) and `gap_not_found`; the timeline shows each attempt.
- A new bot is not on `/bots`: the worker publishes the list at startup. Run `docker compose up -d --build worker`.
- A run stays `queued`: no worker is running. The run page says so. Check with `docker compose ps`.
- No "Watch live" link: it only shows for `headful` runs that are queued or running and that a worker has picked up (`can_watch` in `src/botplatform/web/app.py`). Headless and finished runs have none.
- A run ends `timeout`: a step took too long (the reason names the step), or the whole run passed `RUN_TIME_LIMIT_SECONDS` (reason `run_time_limit`). Raise the limit in `.env`.
- To read logs, run `docker compose logs worker` (or `web`, `db`). Add `-f` to follow.
