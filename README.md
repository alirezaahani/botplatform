# Bot platform

A small platform that runs bots and records every run. A web UI launches a run, a worker executes it (a real Chrome for browser bots), and Postgres holds the queue, the status, the timeline and the screenshots. It ships with two bots: a trivial `example` bot and an ARCaptcha demo-site bot.

```
browser --> web --> Postgres <-- worker(s)
                                 Chrome + Xvfb + noVNC (live view, proxied by web)
```

## Requirements

- Docker with the Compose plugin.
- An amd64 machine. ARM64 is a limitation: it is not supported and has not been tried.

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

Launch an ARCaptcha run in `headful` mode. While it is queued or running, its page at `http://127.0.0.1:8000/runs/<id>` shows a "Watch live" link that opens the worker's browser in noVNC. You can use the mouse and keyboard.

If anyone opens the live view, the run page warns that the result may be human-assisted.

On a server, the port only listens on the server's `127.0.0.1`. Open a tunnel from your own machine, then use the same address in your browser:

```
ssh -L 8000:127.0.0.1:8000 user@server
```

To check that the worker image brings up the display and viewer, run `tests/check_viewer.sh`.

## Scaling

```
docker compose up -d --scale worker=3
```

Each worker runs one bot at a time and claims runs from the database queue, so no two workers take the same run. A worker holds a lease on its run and renews it. If a worker dies, its run is reaped and marked as failed. A run is stopped and marked `timeout` after `RUN_TIME_LIMIT_SECONDS` (180 by default, set in `.env`).

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
TEST_OUTPUT_PLACEHOLDER
```

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

The worker checks the list at startup (unique `id`, non-empty `name` and `modes`) and publishes it, so the new bot appears on `/bots` after you restart the worker (`docker compose up -d --build worker`). `ctx` also offers `record_challenge_id()` and `artifact()`. An uncaught exception is recorded as `error`.

## Stop and reset

```
docker compose down       # stops everything, keeps the run history
docker compose down -v    # also deletes the database volume
```

## Troubleshooting

- `permission denied` from Docker: add your user to the `docker` group (`sudo usermod -aG docker $USER`), then log in again.
- Port 8000 is in use: set `WEB_PORT` in `.env`.
- The first build is slow: it downloads Chrome for Testing. Later builds reuse the cached layers.
