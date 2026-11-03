# Design decisions

## 1. Services: web, worker and database

The web container serves the UI and adds runs to a queue table. The worker takes runs from that table and runs Chrome, the virtual display and noVNC.

**Why:**

- A browser crash or memory spike cannot take down the UI or the run history.
- The execution layer is separate at runtime, not only in the code.
- Chrome stays under the bot's direct control, so the bot can use CDP to read the `create` response. That is the only place we have found `challenge_id` on a blocked run.
- A database table is enough of a queue at this scale, so Redis and Celery are not needed.

**Rejected:**

- **One app container:** a browser failure, or a restart of the UI, would affect both the UI and active runs.
- **A separate Selenium browser container:** `webdriver.Remote` lacks `execute_cdp_cmd`, and the service would be tied to Selenium.

## 2. Bot interface

### 2a. Contract: `run(ctx) -> BotResult`

Each bot implements one Python method and owns its browser. An optional helper covers Selenium setup, and `ctx.record_challenge_id()` writes to the database immediately.

**Why:**

- The core never imports Selenium, so a new engine needs no platform changes.
- The interface is small enough to document with a minimal example.
- A crash after extraction cannot lose `challenge_id`.
- Bots in other languages or services remain possible through an adapter bot, without changing the core. We document this path but do not build it, because nothing needs it yet.

**Rejected:**

- **Platform-created driver, `run(driver, ctx)`:** ties the core to Selenium.
- **Declared steps run by the platform:** builds this one scenario's shape into the core.
- **Bots as HTTP services:** needs registration, health checks, authentication and callbacks, plus a browser and noVNC per bot. The PDF does not ask for other languages.
- **Bots as subprocesses speaking JSON:** adds a protocol and a manifest for the same unneeded language support.

### 2b. Registration: an explicit list

Bots are registered by adding them to the `BOTS` list in `botplatform/bots/__init__.py`. The worker rejects duplicate IDs at startup.

**Why:**

- The whole mechanism is readable in one place, with no import side effects.
- A broken bot fails at worker startup with a normal traceback instead of quietly disappearing.
- The list is in the `bots` package, so adding a bot does not touch the platform core.

**Rejected:**

- **Decorator plus folder scan:** a bot exists only if its file gets imported, and catching import errors can hide a broken bot.
- **Python entry points:** they support separately installed packages, which we do not need, and a new entry point does nothing until the project is reinstalled.

### 2c. Bot list: published by the worker

At startup, the worker upserts every bot in `BOTS` into a `bots` table and marks the rest inactive. The web container only reads that table.

**Why:**

- The database is already the link between web and worker, so this adds a table, not a new connection.
- The web image needs no bot code, Selenium or future engines, and a bot import error cannot break the UI.
- The UI only lists bots the worker has published.

**Costs we accept:**

- The list is empty until the worker first starts, so the UI explains this.
- If the worker is down, the UI still lists its bots and new runs wait in the queue.

**Rejected:**

- **Web imports bot code:** web would need every engine's dependencies.
- **Shared image:** the UI image would carry Chrome, and a bot import error could stop the UI.
- **Separate metadata files:** every bot needs two files that can drift apart.

## 3. Run results

### 3a. Statuses: a generic status plus a bot-supplied reason

The platform owns `queued`, `running`, `success`, `blocked`, `failed`, `timeout` and `error`. A bot adds a short reason code, such as `verification_failed` or `missing_challenge_id`.

| What happened (ARCaptcha bot) | Status | Reason |
|---|---|---|
| Login response and toast both confirm success | `success` | none |
| Login rejected, or the response and toast disagree | `failed` | `verification_failed` |
| No ID, and no block | `failed` | `missing_challenge_id` |
| The server returned `block` | `blocked` | `captcha_blocked` |
| A puzzle appeared and we have no solver | `blocked` | `challenge_unsolved` |
| A step or the whole run ran out of time | `timeout` | the step name |
| A crash, network failure or anything unexpected | `error` | details in the error field |

**Why:** the core stays free of ARCaptcha concepts, and a new bot can add reasons without changing it.

**Rejected:** a single flat list, because each new bot's failure type would mean editing the core.

### 3b. Blocked runs still attempt login

The run enters the credentials and submits, and the login response is saved as evidence. An earlier failure always wins, so login can never upgrade the status.

**Why:** the run follows every step in the PDF, there is one code path to test, and each run records what the server actually did.

**Evidence:** in a manual browser session captured on 2026-11-03 (HAR), `POST /api/login` with an empty `captcha_token` returned HTTP 400 with `{"msg":"Please solve captcha"}`. That session had a puzzle, not a block. We expect the same response after a block because the widget stores no token, but this has not been tested.

**Rejected:** stopping at the block, because the run would skip required steps and record nothing about login.

### 3c. Execution: several workers, each running one bot at a time

Each run happens in a child process. At the time limit, the worker kills the whole process group, including Chrome, and marks the run `timeout`. Scaling means `docker compose up --scale worker=N`, with one worker as the default.

- **Claiming:** workers take runs with `SELECT ... FOR UPDATE SKIP LOCKED`, so two workers cannot claim the same run.
- **Crash recovery:** a worker renews a lease on its run every few seconds, and any worker can mark a run with an expired lease as `error`.

**Why:**

- A hung browser can always be killed, which a thread cannot guarantee.
- Parallel runs need no code changes, and each worker keeps its own display and process.
- `challenge_id` is written as soon as it is obtained, so it survives a kill.

**Rejected:**

- **A thread relying on Selenium's timeouts:** a hang outside those timeouts would stick the worker.
- **Several runs in one worker:** the worker would have to allocate a display and noVNC session per run, and a container failure would take down every active run.
- **One worker with startup cleanup:** simpler, but a second worker starting up would mark the first worker's active runs as `error`.

## 4. Storage

### Database: Postgres on a named volume

**Why:** several containers write to it, and `SKIP LOCKED` needs a database server. The named volume keeps history across container restarts. `docker compose down -v` deletes it, and the README warns about this.

### 4a. Access and migrations: SQLAlchemy and Alembic

A one-shot `migrate` service runs Alembic first, and web and workers wait for it to finish.

**Why:** both libraries are standard, SQLAlchemy supports `SKIP LOCKED`, and Alembic can change tables that already hold history. A separate service stops several workers from racing to apply migrations.

**Rejected:**

- **Plain SQL with numbered files:** we would write our own migration runner and row mapping.
- **`create_all` at startup:** it cannot change existing tables.

### 4b. Run details: `runs` plus an append-only `run_events` table

Every step, every `challenge_id` and the login response go in `run_events`. Passwords are never stored.

**Why:** existing evidence cannot be overwritten, the UI gets a timeline, and any bot can add events without schema changes.

`runs.challenge_id` holds the latest ID, and `run_events` holds every ID. The overlap is deliberate: the column is the current value, and the events are the history. One function writes both in one transaction, and nothing else writes them. The bot records `create` responses in network order, and a test covers two responses in a row.

**Rejected:**

- **A single JSON column:** it mixes everything together, and a bug could overwrite earlier evidence.
- **Only the PDF's columns:** earlier IDs and the login response would be lost.
- **Deriving the latest ID through a view:** there would be one copy, but `runs` would have no `challenge_id` column, and every read would depend on the view.

### 4c. Screenshots: in Postgres, in `run_artifacts`

**Why:** the database stays the only data link between web and worker, and one volume holds all the data. A large number of runs would eventually need cleanup, which this scale does not need yet.

**Rejected:**

- **A shared volume:** it adds a second link, and rows and files can get out of sync.
- **No screenshots:** reviewers would only have our text for what happened.

## 5. Web UI

### 5a. Stack: FastAPI, Jinja and a little htmx

A page showing an active run reloads its status every 2 seconds and stops when the run ends. The htmx file ships in the image, not from a CDN. A run queued for over a minute shows "Still queued. Is the worker running?" with the `docker compose ps` command.

**Why:** it is Python only with no frontend build step, and page data comes only from the database.

**Rejected:**

- **React with a JSON API:** a second language, a build step and much more code that the PDF does not reward.
- **Streamlit:** its rerun model fits poorly with per-run pages and a queue.

### 5b. Pages: `/bots`, `/runs` and `/runs/{id}`

The PDF does not require a JSON API or batch launching, so neither is included.

Each bot declares its modes as plain strings, such as `["headless", "headful"]` or `["direct"]`. The worker publishes them in the `bots` table, and the UI draws one button per mode. Web rejects a mode the bot does not declare, and the worker marks a run `error` if its bot or mode is no longer available. Modes are free-form, so the platform cannot catch a misspelled one, and each bot's test checks its declared modes. The core gives meaning to one string only: `headful` gets the "watch live" link, because the platform provides the viewer.

**Why:** the platform does not assume every bot is a browser, so a new kind of bot needs no core change and the history records what actually happened. One-click buttons also make the mode explicit on every launch, with no default to forget about.

**Rejected:**

- **A fixed list of modes in the core:** any new kind of bot would mean editing the core.
- **Only headless and headful:** a future HTTP bot would have to record a false mode.
- **A radio button and a Launch button:** it adds a click, and a preselected mode is easy to launch by accident.

### 5c. Access: localhost by default, no login

Ports bind to `127.0.0.1`. On a server, access goes through an SSH tunnel, and the README gives the exact command.

**Why:** it is safe by default with nothing to build or configure, and the live view goes through the same port.

**Rejected:**

- **A password from `.env`:** basic auth over plain HTTP is weak, and it adds setup for reviewers.
- **Open with no login:** anyone who can reach the page could launch browsers.

## 6. Headful viewing

### 6a. Mechanism: noVNC in the worker

Each worker runs Xvfb, x11vnc and noVNC all the time, under a small start script that exits if any of them dies, so Docker restarts the container.

**Why:** the steps are almost the same on desktop and server, and the viewing machine needs only a browser.

**Rejected:**

- **X11 forwarding to the host:** mainly a Linux solution with no screen to use on a server, so we would document two methods.
- **A plain VNC port:** every reviewer would have to install a client.

### 6b. Control: interactive

Viewers can use the mouse and keyboard in the browser.

**Why:** being able to step in makes debugging easier.

**Cost we accept:** a person could affect a run, for example by solving the puzzle, so the history alone cannot prove a result came from the bot.

**Mitigation:** the proxy adds a `viewer_connected` event, and the run page warns that the result may be human-assisted. This shows a viewer was connected, not whether they did anything. Bonus success rates can exclude these runs.

**Rejected:** view only, which rules out debugging by hand.

### 6c. Reaching a worker: web proxies the viewer

`/runs/{id}/live` connects through web to the worker in `runs.worker_id`. Worker viewer ports are not published, so only web's port is exposed.

**Why:** there is one URL at any scale, with no port range or lookup, and a server needs only the one SSH tunnel.

**Cost we accept:** web now talks directly to workers for the live view, and needs a WebSocket proxy. The database remains the only link for data and coordination, so a proxy failure affects only live viewing.

**Rejected:**

- **A port range with a lookup command:** viewing is a manual step when scaled.
- **Only the first worker runs headful:** the queue would need routing, and Compose a second worker service.

## 7. Tests

### 7a. Bot tests: real Selenium against a local fake demo page

A fake server returns any outcome on demand, and a separate command runs against the live site.

**Why:** the required failures are repeatable without relying on ARCaptcha or the IP, while real selectors and network capture still get exercised. The live command catches drift between the fake page and the real site.

**Rejected:**

- **A mocked driver:** it only tests our assumptions about the browser.
- **Live site only:** we cannot trigger a timeout or a login failure on demand.

### 7b. Where tests run: Docker only

Tests use the worker image and a real Postgres, through one Compose command.

**Why:** reviewers need only Docker, the tests use the browser we ship, and `SKIP LOCKED` is tested for real.

**Cost we accept:** tests run more slowly during development.

**Rejected:**

- **Local `uv` and Chrome:** browser versions vary and reviewers must install more.
- **SQLite:** it cannot test `SKIP LOCKED`.

### 7c. Results: saved output plus GitHub Actions

The README includes real test output. CI runs the tests and a `docker compose up` check on every push.

**Why:** CI catches many fresh-setup failures on a clean machine. It does not replace the final test on a fresh VM using only the README.

**Rejected:** saved output only, which shows only what happened on one machine.

## 8. Delivery plan

### Build order: a thin end-to-end version first

1. Compose, Postgres, migrations, web, worker and the `direct` example bot
2. Selenium bot, run against the live site from Docker
3. Fake demo page and bot tests
4. Xvfb, noVNC, the proxy and the viewer warning
5. Timeouts, leases, scaling and platform tests
6. GitHub Actions and the README
7. Fresh VM test using only the README, then submit

**Why:** something always runs, so running short of time cuts features, not the core workflow. The riskiest unknowns surface in step 2.

### Bonus: decide after step 2, start after step 5

The bonus must stop by Friday morning, so the README and VM test keep their time.

## Platform support

amd64 only. ARM64 was not considered, and the README states this limitation.

## Meaning of a blocked run

A blocked run is a failed run, even when `challenge_id` was recorded, because the required scenario also includes logging in and verifying the result. The run stays visible in the history with its `challenge_id`.
