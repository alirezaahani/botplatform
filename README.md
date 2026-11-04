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

## Using it

- `/bots`: the registered bots and their modes, with a launch button for each. The newest bot is first. The list has the baseline `arcaptcha`, one `arcaptcha-<profile>` bot per browser profile, the assisted bot `arcaptcha-assisted`, the experiment `arcaptcha-drag-probe`, the four `arcaptcha-solver-*` bots, and the `example` bot.
- `/bonus` and `/bonus.md`: the bonus report, for each bot and mode, how often the site did not block the bot (filters `?bot=` and `?since=`). "Not blocked" means that the first `create` answer of a run had a CAPTCHA type other than `block`. It does not mean the run succeeded.
- `/runs`: the run history.
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

To check that the worker image brings up the display and viewer, run `tests/check_viewer.sh`.

## Reducing CAPTCHA blocking (bonus)

The approach: the site blocks the plain bot at the first `create` request, so the bot can take a different browser profile (`src/botplatform/profiles.py`): Chrome arguments, dropped Selenium switches and a start-up script that hides automation signals. Each profile is its own registered bot, `arcaptcha-<profile>`, so every run lands in the normal run history, and the history is the evidence. `all-signals` combines the three single-factor profiles and is meant for `headful`. `all-signals-headless` adds a normal user agent and screen size, and is meant for `headless`.

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
docker compose run --rm -T web python -m botplatform.batch --profiles all-signals --modes headful --runs 10 --stop-after 0 --pause 5 --jitter 3
```

The worker must be running. The batch queues runs one at a time through the normal queue, waits for each, and prints one line per run (`number/total bot mode status reason challenge_id seconds`), then a summary per bot and mode. Each run takes about 15 seconds. It talks to the live demo site, so it is not part of the tests.

| Option | Default | Meaning |
|---|---|---|
| `--profiles` | all profiles | Comma separated profile names. |
| `--modes` | `headless,headful` | Comma separated modes. |
| `--runs` | 10 | Runs per profile and mode. |
| `--pause`, `--jitter` | 10, 5 | Seconds between runs, plus a random 0 to `jitter` seconds. |
| `--run-timeout` | 240 | Seconds to wait for one run. |
| `--stop-after` | 5 | Skip the rest of a bot and mode after this many `blocked` runs in a row. 0 never stops. |
| `--seed` | random | Shuffle seed, to repeat an order. |

Then open `/bonus` (or `/bonus.md`, add `?bot=arcaptcha-all-signals` or `?since=2026-11-04T09:00` to filter). Each row is a bot and mode: the outcomes, the `create` types, the not-blocked count with a 95% Wilson interval, and how many runs got a `challenge_id`. Runs where someone opened the live viewer are left out of the rates and counted in "Excluded".

### The assisted bot

`arcaptcha-assisted` is a diagnostic, `headful` only. It asks whether the site accepts a correct slider answer from this browser, by letting a person solve the slider:

1. Launch `arcaptcha-assisted` from `/bots`.
2. Open the run page and click "Watch live" within about 2 minutes (the bot waits about 130 seconds for the puzzle to be solved).
3. Drag the slider in the live viewer.
4. The bot sees the accepted answer and logs in.

Status `success` with reason `human_solved` means a person solved the puzzle. It is not a bot success. Result: in 7 runs, every correct answer was accepted and every login was verified. One run also had a deliberately wrong answer first, which the site rejected and replaced with a new puzzle. The evidence is in [evidence/bonus/assisted/](evidence/bonus/assisted/README.md).

## Solving the slider (the solver bots)

Four automatic bots, all `headful`, with the `all-signals` browser profile. Each is a pair of a gap finder and a movement shape:

| Bot | Finds the gap with | Moves the handle |
|---|---|---|
| `arcaptcha-solver-cv-linear` | `cv`: detects the light halo around the gap and measures its body square | 8 equal steps, about 0.6 s |
| `arcaptcha-solver-cv-eased` | `cv` | ease-out over 25 to 40 steps, 0.8 to 1.5 s, 1 to 2 px vertical wobble |
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

Live results, headful, one IP, 2026-11-04: each of the four bots was run 10 times, interleaved, 15 seconds apart. All 40 runs ended `success` / `solved`, all on the first attempt, with a median run of about 16 s. Table and per-run rows: [evidence/solver/results-headful-2x2.md](evidence/solver/results-headful-2x2.md).

Limits, stated plainly:

- 40 of 40 does not mean a 100% success rate: with no failures it only says the failure rate is probably below about 7%. It also does not separate the four bots; neither the finder nor the movement shape changed whether the site accepted the answer.
- One IP, one evening and headful only. Another network, time of day or mode may differ, and a site that scores movement could change without notice.
- The 40-run comparison was driven by a small shell loop that posts to `/bots/<bot id>/runs` with `mode=headful` and waits for each run. The batch runner above works on browser profiles and does not run these bots.
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

This needs only Docker and no `.env`. It uses its own project name and a throwaway Postgres, so it never touches the main stack. The bot tests run real Chrome against a fake ARCaptcha demo page served by pytest. The fake can return any outcome on demand (a block, a puzzle, a hang, a dropped connection), so every failure path is repeatable without the live site.

To check the fake against the real site, run the live test (needs internet):

```
docker compose -f compose.test.yaml run --rm --build tests pytest -m live -v -s
```

CI (`.github/workflows/ci.yml`) runs the tests, then starts the stack and launches a run of each bot. You can run that check locally with `.github/scripts/smoke.sh`.

Real output of the test command:

```
=========== 222 passed, 1 deselected, 1 warning in 293.70s (0:04:53) ===========
(the deselected test is the live test)
```

Known flaky test: `test_a_second_puzzle_after_a_rejected_answer_is_number_two` in `tests/test_puzzle_capture.py` has failed in some full runs and passed alone and in others. A fake person answers a puzzle faster than the bot polls, so the two `create` responses can arrive together and the bot captures only the latest. A real person cannot do that. It is not fixed.

### What the tests cover

Bot cases are in `tests/test_bot.py` and use the fake demo page. Platform cases are in the other files. The bonus work adds the rows at the end of the table. Each row lists the status and reason that the test asserts.

| Case | Test | Result |
|---|---|---|
| Main success workflow | `test_accepted_checkbox_then_confirmed_login_succeeds` (types `accept` and `cookie`), `test_softban_with_confirmed_login_succeeds` | `success` |
| Missing `challenge_id` | `test_accept_without_id_fails` | `failed`, `missing_challenge_id` |
| CAPTCHA blocking | `test_block_with_id_records_the_id_and_still_logs_in`, `test_block_without_id`, `test_successful_login_never_upgrades_a_block` | `blocked`, `captcha_blocked` |
| Puzzle or unsolved challenge | `test_challenges_are_blocked_as_unsolved` | `blocked`, `challenge_unsolved` |
| Step timeouts | `test_page_load_hang`, `test_checkbox_missing`, `test_create_hang`, `test_login_response_hang` | `timeout`, reason is the step: `load_page`, `find_checkbox`, `create_response`, `login_response` |
| Whole-run timeout | `test_a_hung_child_and_its_grandchild_are_killed_at_the_time_limit` in `tests/test_worker.py` | `timeout`, `run_time_limit` |
| Unsuccessful form verification | `test_softban_with_rejected_login_fails_verification`, `test_login_not_confirmed_by_both_signals_fails` | `failed`, `verification_failed` |
| Dropped connections | `test_create_connection_dropped_is_an_error_straight_away`, `test_login_connection_dropped_is_an_error`, `test_create_api_origin_refuses_connections` | `error`, `create_request_failed` or `login_request_failed` |
| Dropped login after a block | `test_blocked_run_whose_login_is_dropped_stays_blocked`, `test_blocked_run_whose_login_hangs_stays_blocked` | `blocked`, `captcha_blocked` |
| Queue claim | `test_claim_is_fifo`, `test_claim_marks_the_run_running_with_a_lease`, `test_concurrent_claims_never_duplicate_or_lose_a_run` in `tests/test_queue.py` | one claim per run |
| Leases and reaping | `test_renew_extends_the_lease`, `test_reap_expired_marks_only_expired_running_runs`, `test_a_late_finish_after_reaping_changes_nothing` in `tests/test_queue.py`; `test_the_lease_is_renewed_while_the_child_runs`, `test_losing_the_lease_kills_the_child_and_keeps_the_reapers_status` in `tests/test_worker.py` | `error`, `worker_lost` |
| Worker crash and stop | `test_a_child_that_exits_without_a_result_is_bot_process_died`, `test_sigterm_kills_the_child_and_marks_the_run_worker_stopped` in `tests/test_worker.py` | `error`, `bot_process_died` or `worker_stopped` |
| Viewer proxy | `test_live_redirects_to_novnc_through_the_proxy`, `test_websocket_carries_bytes_both_ways`, `test_websocket_closes_when_the_run_ends`, `test_proxy_refuses_runs_that_cannot_be_watched`, `test_watch_live_link_rules` in `tests/test_viewer.py` | proxy and link rules |
| Browser profiles | `tests/test_profiles.py` (26 tests): each profile changes what the page sees (`navigator.webdriver`, `cdc_` names, WebGL, user agent, screen size) and not before page scripts; every profile has a registered bot; the run records the profile, the browser signals and the decoded `create` request | profile and recording rules |
| Batch runner | `tests/test_batch.py` (13 tests): plan size and seeded shuffle, pause and jitter, the early stop, Ctrl-C, a run that never finishes, and a batch against the real queue with a stand-in worker | batch output and stop rules |
| Interval maths | `tests/test_stats.py` (6 tests): the 95% Wilson interval, including 0 of n, n of n and impossible counts | interval values |
| Bonus report | `tests/test_bonus.py` (6 tests): per bot and mode counts, the first `create` answer only, viewer runs excluded, `?since=` and `?bot=`, `/bonus.md` header, empty history | rates and filters |
| Assisted bot | `tests/test_assisted.py` (11 tests): a solved puzzle then a verified login is `success`, `human_solved`; a rejected answer brings a second puzzle; nobody answering is a timeout; a failed login after a solve is `verification_failed`; it is registered `headful` only | `success`, `human_solved` and the failure cases |
| Newest first | `tests/test_order.py` (4 tests): the `BOTS` order, `publish` sets and updates `position`, the Bots page and the Bonus report list the newest bot first | page and report order |
| Puzzle capture | `tests/test_puzzle_capture.py` (5 tests): a puzzle is saved as two artifacts and an event, a second puzzle after a rejected answer is number two and pairs with its answer by `challenge_id`, broken images record a failure and leave the result unchanged | artifacts and `puzzle_captured` events |
| Drag probe | `tests/test_drag_probe.py` (10 tests): both drag methods alternate, samples show the handle-to-piece ratio, a raising attempt is recorded, the budget and an accepted answer stop the probe | `blocked`, `drag_probe_done` |
| Gap finders | `tests/test_solver_gap.py` (19 tests): the `cv` finder returns the expected target on 8 real puzzles (stored in `tests/fixtures/solver/`) and raises `GapNotFound` on blank or garbage input; `tests/test_solver_silhouette.py` (18 tests): the same 8 puzzles for the silhouette finder, plus noise, garbage, a piece without alpha and a row outside the image | the answer in px, or `GapNotFound` |
| Movement | `tests/test_solver_movement.py` (14 tests): both paths end exactly on the target, durations and wobble stay in bounds with a seeded generator, edge cases of 0 and 196 px | path shape |
| Solver bots | `tests/test_solver_bot.py` (10 tests): all four bots solve a real fixture puzzle on the fake page, a wrong first target is rejected and then solved, three rejections end `blocked`, no gap ends `blocked` without a drag, a handle that ignores the first press is pressed again without counting as an attempt | `success`, `solved` and the failure cases |

## Adding a bot

A bot is a class that implements the contract in `src/botplatform/contract.py`:

```python
from typing import ClassVar

from botplatform.contract import Bot, BotResult, RunContext, Status


class HelloBot(Bot):
    id = "hello"
    name = "Hello bot"
    description = "Adds one event and succeeds."
    modes: ClassVar[list[str]] = ["direct"]

    def run(self, ctx: RunContext) -> BotResult:
        ctx.event("hello", {"mode": ctx.mode})
        return BotResult(status=Status.SUCCESS)  # or e.g. Status.FAILED, reason="my_reason"
```

Then register it in the explicit list in `src/botplatform/bots/__init__.py`. Append new bots at the **end** of `BOTS`: the list order is the order bots were added, and the UI shows the newest (last) first.

```python
BOTS: list[type[Bot]] = [ExampleBot, ArcaptchaBot, ..., ArcaptchaAssistedBot, HelloBot]
```

A browser variant of the ARCaptcha bot needs no new class: it is one entry in `PROFILES` in `src/botplatform/profiles.py`, which registers a bot `arcaptcha-<name>`.

The worker checks the list at startup (unique `id`, non-empty `name` and `modes`) and publishes it, so the new bot appears on `/bots` after you restart the worker (`docker compose up -d --build worker`). `ctx` also offers `event()`, `record_challenge_id()` and `artifact()`. An uncaught exception is recorded as `error`.

You can use another automation engine, such as Playwright, in the same way. The contract only needs `run(ctx) -> BotResult`, and the core never imports Selenium. Only `src/botplatform/bots/selenium_support.py` is Selenium-specific: the `chrome()` launcher, the alert helper and `ResponseWatcher`. It is an optional helper. A bot with another engine would start its own browser, and send screenshots with `ctx.artifact(name, "image/png", data)` and timeline entries with `ctx.event()`. Nothing in this repo has a Playwright bot, and Playwright is not a dependency. Its browser would also have to be installed in the worker image.

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
