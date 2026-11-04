# Bot platform

A small platform that runs bots and records every run. A web UI launches a run, a worker executes it (a real Chrome for browser bots), and Postgres holds the queue, the status, the timeline and the screenshots. It ships with two bots: a trivial `example` bot and an ARCaptcha demo-site bot.

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

- `/bots`: the registered bots and their modes, with a launch button for each.
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
=========== 80 passed, 1 deselected, 1 warning in 128.00s (0:02:08) ============
(the deselected test is the live test)
```

### What the tests cover

Bot cases are in `tests/test_bot.py` and use the fake demo page. Platform cases are in the other files. Each row lists the status and reason that the test asserts.

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

Then register it in the explicit list in `src/botplatform/bots/__init__.py`:

```python
BOTS: list[type[Bot]] = [ExampleBot, ArcaptchaBot, HelloBot]
```

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
- A run ends `blocked`: the site refused the bot or showed a puzzle (`captcha_blocked`, `challenge_unsolved`). This is a recorded result, not a bug. The `challenge_id` is kept on the run page.
- A new bot is not on `/bots`: the worker publishes the list at startup. Run `docker compose up -d --build worker`.
- A run stays `queued`: no worker is running. The run page says so. Check with `docker compose ps`.
- No "Watch live" link: it only shows for `headful` runs that are queued or running and that a worker has picked up (`can_watch` in `src/botplatform/web/app.py`). Headless and finished runs have none.
- A run ends `timeout`: a step took too long (the reason names the step), or the whole run passed `RUN_TIME_LIMIT_SECONDS` (reason `run_time_limit`). Raise the limit in `.env`.
- To read logs, run `docker compose logs worker` (or `web`, `db`). Add `-f` to follow.
