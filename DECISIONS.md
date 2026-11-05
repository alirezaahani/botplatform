# Design decisions

## 1. Services: web, worker and database

The web container serves the UI and adds runs to a queue table. The worker takes runs from that table and runs Chrome, the virtual display and noVNC.

**Why:**

- A browser crash or memory spike cannot take down the UI or the run history.
- The execution layer is separate at runtime, not only in the code.
- Chrome stays under the bot's direct control, so the bot can use CDP to read the `create` response. That is the only place we have found `challenge_id` on a blocked run.
- A database table is enough of a queue at this scale, so Redis and Celery are not needed.
- The database already holds the run status, results and history. A broker would keep a second copy of that state, and the two could disagree after a crash, for example a job acked in Redis but never recorded in the database.
- A run opens a real Chrome and takes seconds to minutes, so volume is at most a few claims per second. A poll every second (`worker_poll_seconds`) costs nothing at that rate, and a broker's low-latency delivery would not help.
- The queue is a table, so "what is waiting?" is a plain SQL query, and the UI uses it for the "Still queued" hint. Runs are durable rows, so there are no broker persistence settings to get wrong.
- Several workers claim safely with `SELECT … FOR UPDATE SKIP LOCKED`, so no two workers take the same run.

**Cost we accept:**

- A run can wait up to about one second before a worker picks it up.
- The polling puts a small constant load on the database.
- It does not scale to thousands of jobs per second. Above that, a broker would be the right choice, and the table would stay the source of truth for run state.
- There are no built-in retries, priorities or delayed jobs. We would write them ourselves if we needed them.

**Rejected:**

- **Redis or RabbitMQ (with Celery or a similar worker library):** one more service to run and configure, and a second place for run state, for a load a Postgres table handles easily.
- **One app container:** a browser failure, or a restart of the UI, would affect both the UI and active runs.
- **A separate Selenium browser container:** `webdriver.Remote` lacks `execute_cdp_cmd`, and the service would be tied to Selenium.

### 1a. Browser: Chrome for Testing

The worker image installs one pinned version of Chrome for Testing and its matching chromedriver, currently 156.0.8078.80. Selenium gets the driver path directly, so Selenium Manager never downloads anything.

**Why:** the browser and driver always match, and a rebuild on a fresh machine gets the same version.

**Cost we accept:** it is a testing build, and we have not measured how that affects the block rate.

**Rejected:**

- **Google Chrome stable:** closest to what real users run, but the apt repo only serves the latest version, so a rebuild can change the browser. It remains a simple comparison if we need one.
- **Debian `chromium`:** the simplest install, but Debian decides the version, and it is the furthest from real Chrome.

**Sandbox:** Chrome runs with `--no-sandbox`. Measured on 2026-11-03 on one host, with the worker image and Chrome 156:

| Docker seccomp | `--no-sandbox` | Result |
|---|---|---|
| default | no | Chrome crashes: `FATAL ... No usable sandbox!` |
| default | yes | works |
| `--security-opt seccomp=unconfined` | no | works |

**Why we keep the flag:** the bot visits one fixed site and runs as a non-root user inside a container. A custom seccomp profile is another file to maintain, and it could fail on a reviewer's machine. `seccomp=unconfined` weakens the container more than the flag does.

### 1b. Image layers: slow steps first

The Chrome download has its own build stage that depends only on the version. Each image installs its dependencies before copying `src`, and a BuildKit cache mount keeps uv's downloads.

**Why:** a source edit used to invalidate the Chrome and package layers, which downloaded everything again on each rebuild. In one measurement, the first build took 13m21s, about 12 minutes of it in the Chrome stage, and a source-only rebuild took 0.8s.

**Cost we accept:** a fresh machine still downloads everything once, so the VM test and CI need time for that.

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

Bots are registered by adding an instance to the `BOTS` list in `botplatform/bots/__init__.py`. The worker rejects duplicate IDs at startup.

**Why:**

- The whole mechanism is readable in one place, with no import side effects.
- A broken bot fails at worker startup with a normal traceback instead of quietly disappearing.
- The list is in the `bots` package, so adding a bot does not touch the platform core.
- Bots are instances, not classes, so one class plus a spec (`BotSpec` for ARCaptcha) covers every variant: no `type()` factories or `ClassVar` tricks.

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
| Login rejected, or the response and toast disagree (or no toast appears) | `failed` | `verification_failed` |
| No ID, and no block | `failed` | `missing_challenge_id` |
| The server returned `block` | `blocked` | `captcha_blocked` |
| A puzzle appeared and we have no solver | `blocked` | `challenge_unsolved` |
| A solver bot: the answer was accepted and the login verified | `success` | `solved` |
| A solver bot: 3 answers in a row were rejected | `blocked` | `solve_failed` |
| A solver bot: the finder found no gap | `blocked` | `gap_not_found` |
| A step or the whole run ran out of time | `timeout` | the step name |
| The `create` or login request failed before any response (dropped connection, refused port) | `error` | `create_request_failed` or `login_request_failed` |
| A crash or anything else unexpected | `error` | details in the error field |

**Why:** the core stays free of ARCaptcha concepts, and a new bot can add reasons without changing it.

**What counts as `success`:** the login response is HTTP 200, the toast has the success style, and the toast text contains the response's `msg`. Anything else is `verification_failed`. This has been seen on the live site: every assisted run (7, a bot since removed) and every solver run (46) that reached login returned HTTP 200 with the success toast and the matching `msg`.

**Rejected:** a single flat list, because each new bot's failure type would mean editing the core.

### 3b. Blocked runs still attempt login

The run enters the credentials and submits, and the login response is saved as evidence. An earlier failure always wins, so login can never upgrade the status.

This applies to runs already classified as failed, blocked, or `error` with `create_request_failed` or `unknown_captcha_type`: all of these are classified failures, and the run stays in that status whatever the login does. A timeout before the login step (page load, finding the checkbox, or no `create` response, including a `create` that hangs without failing) ends the run without attempting login.

**Why:** the run follows every step in the PDF, there is one code path to test, and each run records what the server actually did. After an early timeout, the page may not be usable, so a login attempt would show little and could use up the remaining run time.

**Evidence:** in all 10 live runs on 2026-11-03, each of them blocked, `POST /api/login` returned HTTP 400 with `{"msg":"Please solve captcha"}`, and a red toast showed the same text (see section 8).

**Rejected:** stopping at the block, because the run would skip required steps and record nothing about login.

### 3c. Execution: several workers, each running one bot at a time

Each run happens in a child process. At the time limit, the worker kills the whole process group, including Chrome, and marks the run `timeout`. Scaling means `docker compose up --scale worker=N`, with one worker as the default.

- **Claiming:** workers take runs with `SELECT ... FOR UPDATE SKIP LOCKED`, so two workers cannot claim the same run.
- **Crash recovery:** a worker renews a lease on its run every 5 seconds (`lease_renew_seconds`), and the lease lasts 30 seconds (`lease_seconds`). Before each claim, every worker marks runs with an expired lease as `error` with reason `worker_lost`, so no leader or separate reaper is needed. The database clock decides expiry, so container clock differences do not matter. A false reap needs six missed renewals in a row.
- **Renewal without a thread:** the worker waits for the child in 5-second slices and renews in each slice. If a renewal finds the run no longer its own (another worker reaped it), the worker kills the child's process group.
- **Graceful stop:** on `SIGTERM` the worker kills the child's process group and marks the run `error` with reason `worker_stopped`.
- **No automatic retry:** a lost run is `error`, not re-queued, because a run logs in on a real site and a repeat could duplicate that side effect.

**Evidence (2026-11-04, `--scale worker=2`, real runs started from the UI):** `docker kill` of the worker that held a run: the other worker marked it `error`/`worker_lost` 25 seconds later. `docker stop` of the holder: the run became `error`/`worker_stopped` within 5 seconds. Both showed correctly on the run page and in the history. Platform tests (`tests/test_queue.py`, `tests/test_worker.py`) cover claim order, concurrent claims with no duplicate, lease renewal and reaping, the time limit killing a grandchild process, a child that exits with no result, and `SIGTERM`.

**Cost we accept:**

- A worker busy with a run does not reap, so a lost run waits until some worker is idle. With one worker, recovery happens after it restarts.
- A `SIGTERM` between claiming and starting the child leaves the run `running` until the lease expires, then `worker_lost`.
- `lease_expires_at` keeps its last value after a run ends. Only `running` rows are checked, so it has no effect.
- A database outage during renewal stops the worker, and Compose restarts it.

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

Every step, every `challenge_id` and the decoded login request and response go in `run_events`. The bots log in with the public demo account, so nothing is redacted (see "Redaction removed" below).

**Why:** existing evidence cannot be overwritten, the UI gets a timeline, and any bot can add events without schema changes.

`runs.challenge_id` holds the latest ID, and `run_events` holds every ID. The overlap is deliberate: the column is the current value, and the events are the history. One function writes both in one transaction, and nothing else writes them. The bot records `create` responses in network order, and a test covers two responses in a row.

**Rejected:**

- **A single JSON column:** it mixes everything together, and a bug could overwrite earlier evidence.
- **Only the PDF's columns:** earlier IDs and the login response would be lost.
- **Deriving the latest ID through a view:** there would be one copy, but `runs` would have no `challenge_id` column, and every read would depend on the view.

**Event IDs are UUIDs, ordered by `at`:** `run_events` was the only table with an integer key, and that integer also gave the timeline its order. It now has a UUID `id` like `runs` and `run_artifacts`, and the timeline orders by `at`, as artifacts order by `created_at`. UUIDv7 would keep the order in the ID, but it needs Python 3.13 and Postgres 18.

**Trade-off:** a clock that steps backwards during a run could misorder its events, and events written in one transaction share an `at`, so their order among themselves is not defined. Migration 0004 discards the old integer IDs. Downgrading numbers the events 1..n in `at` order.

**Database sessions:** `db.py` creates one engine and one session factory (`SessionLocal`) when it is imported. Web routes get one session per request through `Depends`, and everything else opens a short `with SessionLocal() ...` block (`begin()` to write). Helpers take a `session` argument. The old `lru_cache` factory was lazy, and passing it around only hid that there is one engine per process.

`launch_run` still commits explicitly. Committing when the dependency exits can happen after the response is sent, depending on the FastAPI version, so the browser could follow the redirect to a run that does not exist yet.

**Trade-off:** importing `botplatform.db` now needs `DATABASE_URL` set, because `Settings()` is read at import. Compose gives it to `web`, `worker` and `migrate`, and the test compose file sets it too.

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

**Run end:** the proxy closes the connection when the run ends, because the display belongs to the worker and the next run would otherwise be watched without a warning. Cost: a viewer must reconnect for the next run, and the check adds a small DB read every 2 seconds per viewer.

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

The fake is FastAPI and uvicorn, started inside pytest, so only the test image carries them. It runs two servers on different ports, so the `create` API is truly cross-origin and Chrome sends a real CORS preflight. Each test sets the outcome in Python: any `captcha_type`, a hang, a dropped connection, an HTTP error, or a toast that disagrees with the response. The tests give the bot short timeouts through `ArcaptchaBot(BASELINE_SPEC, url=..., timeouts=StepTimeouts(...))`. The production worker runs the registered `BASELINE_BOT`, which has the defaults.

**Result:** step 3 ran 50 tests (bot tests against the fake, plus codec and mode tests) in 92.2s, all passed (`pytest` in the test image, 2026-11-04). The live drift test was not part of that run.

**What the fake cannot prove:** it copies what we saw on the real site and what we read in the widget code. A pass on the fake only confirms our assumptions. The live command (`pytest -m live`) is the check for drift.

**Rejected:**

- **A mocked driver:** it only tests our assumptions about the browser.
- **Live site only:** we cannot trigger a timeout or a login failure on demand.

### 7b. Where tests run: Docker only

Tests use the worker image and a real Postgres, through one Compose command.

**Why:** reviewers need only Docker, the tests use the browser we ship, and `SKIP LOCKED` is tested for real.

Tests use their own file, `compose.test.yaml`: `docker compose -f compose.test.yaml run --rm --build tests` (`--build` matters: the tests are copied into the image, so without it an old image runs old tests). It has its own project name, `botplatform-test`, so it cannot touch the main stack's containers or database volume. It needs no `.env`. It starts a throwaway Postgres (no volume) for the web tests, and the tests create the tables with `create_all`. The `test` image stage reuses the worker's Chrome and system layers and adds pytest and FastAPI, so production images gain neither. Live tests are off by default: `... run --rm --build tests pytest -m live -v -s`.

**Cost we accept:** tests run more slowly during development.

**Rejected:**

- **Local `uv` and Chrome:** browser versions vary and reviewers must install more.
- **SQLite:** it cannot test `SKIP LOCKED`.

### 7c. Results: saved output plus GitHub Actions

The README includes real test output. CI runs the tests and a `docker compose up` check on every push.

**Why:** CI catches many fresh-setup failures on a clean machine. It does not replace the final test on a fresh VM using only the README.

**Rejected:** saved output only, which shows only what happened on one machine.

**CI smoke run against the live site:** the `stack` job (`.github/scripts/smoke.sh`) starts the stack, launches one run of the example bot and one headless ARCaptcha run, and reads their final status from Postgres. The example bot must end `success`. The ARCaptcha run is accepted as `success`, `blocked` or `failed`, because that outcome depends on ARCaptcha and the runner's IP, not on our code. A `success` or `blocked` run must also have a `challenge_id`.

**Why:** a terminal status with a recorded `challenge_id` shows the whole path works on a clean machine: build, migrations, queue, worker, Chrome, the live request and the database write.

**Cost we accept:** the job needs the live site to be reachable, so an outage on their side can turn CI red. `error` and `timeout` fail the job, because they point to a platform problem (or an unreachable site, which we cannot tell apart from here). A green job does not mean the login succeeded.

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

### Step 2 results: every live run was blocked

Ten headless runs from Docker on 2026-11-03, using plain Chrome for Testing with no measures against blocking:

| Question | Result |
|---|---|
| Block rate | 10 of 10 blocked, and each run recorded its own 30-digit `challenge_id` |
| Login after a block | HTTP 400 with `{"msg":"Please solve captcha"}`, and a red toast with the same text |
| `getChallengeID()` on a blocked run | Empty on all 10, as were `getArcToken` and the hidden field, so the decoded `create` response is the only source |

**Limits of this evidence:**

- The cause of the block is unknown, because the server makes the decision.
- All runs came from one machine and one IP, and headful has not been measured from Docker.
- These outcomes have not occurred on the live site: `success`, a green toast, a puzzle, `accept`, a JS alert, a timeout, `missing_challenge_id` and `unknown_captcha_type`. The fake demo page has to cover them, which can only confirm our assumptions about the real success path.

### Step 4 results: live viewing

Built: the worker image runs `worker/start.sh` (Xvfb `:99` at 1280x800x24, x11vnc on localhost, websockify serving noVNC on port 6080, then the worker). If any of them dies, the script exits non-zero and Docker restarts the container. The `arcaptcha` bot now declares `headless` and `headful`. Web proxies `/runs/{id}/live` (static files and the WebSocket) to the run's worker, adds a `viewer_connected` event per connection, and the run page shows a "Watch live" link and the human-assisted warning.

Measured on 2026-11-04, one host, Chrome 156:

| Check | Result |
|---|---|
| Full test suite in Docker (`compose.test.yaml`) | 65 passed (1 live test deselected), 92s |
| `tests/check_viewer.sh` on the worker image | Xvfb `:99`, x11vnc on 5900 and noVNC on 6080 all up |
| Headful ARCaptcha run through the stack | ran on Xvfb and ended `blocked` / `captcha_blocked`, like headless |
| `/runs/{id}/live` while the run was active | redirected to noVNC, which came through the proxy; the WebSocket proxy gave the RFB handshake (`RFB 003.008`) |
| `viewer_connected` and the warning | event written, warning on the run page |
| Keyboard and mouse focus, no window manager | Chrome had focus (`document.hasFocus()` true) and text sent as VNC key events reached the page. Checked with a scripted RFB client, not by hand in a browser |
| Kill Xvfb in the worker | container restarted (restart count 1) and the viewer came back |
| `docker compose up -d --scale worker=2` | web resolved both workers' hostnames and reached both noVNC ports |

**Not verified:** a person using the viewer in a real browser (no browser tool was connected), and a human actually driving a live run, because blocked runs finish within seconds.

**Choices:**

- **No window manager.** Chrome gets keyboard focus without one in the check above. **Why:** one less process to run and fail. **Cost we accept:** no window decorations, and a second Chrome window (a dialog) has no focus handling.
- **Screen 1280x800.** Chrome is started with the same size and position, so it fills the screen. **Why:** it fits most laptop screens when scaled in the viewer. **Cost we accept:** a fixed size for every headful run.
- **The worker is found by its container hostname**, which is `runs.worker_id`. **Why:** Compose's DNS already resolves it, with nothing to register. It resolved for both workers when scaled to 2. **Cost we accept:** it depends on Compose networking, and the lookup function (`worker_base_url`) is the one place to change otherwise.
- **The viewer port has no password.** x11vnc listens on localhost inside the worker, and websockify's port 6080 is not published, so only containers on the Compose network can reach it. **Why:** the only way in from outside is web's port, which binds to `127.0.0.1` (5c). **Cost we accept:** anything else on the Compose network could take control of a run.

### Bonus: a time-boxed attempt after step 5

We will start the bonus after step 5, as planned. It must stop by Friday morning, so the README and VM test keep their time.

**Why:** step 3 onwards is required work, and the bonus is not. Fewer blocks may also not be enough to reach `success`, because manual Chrome always got the slider puzzle, so the bot would probably also need a slider solver.

Blocked and failed attempts are reported as they happened, whatever the bonus achieves.

#### Bonus (a): profiles and probe bots

**What:** a `Profile` (`profiles.py`, outside the `bots` package so the web image can import it without Selenium) is a named set of Chrome arguments, dropped Selenium switches and an optional start-up script. `chrome(profile=...)` applies it. There are two now: `baseline` (today's behaviour, nothing added) and `stealth-flags`. Every non-baseline profile gets its own registered bot, `arcaptcha-<profile>`; `arcaptcha` stays the baseline with its old name. Adding a profile is one entry in `PROFILES`. Every ARCaptcha run records `browser_profile` (the settings used), `browser_signals` (what the page can see about the browser) and `create_request` (the decoded `create` request, which carries the signals the server receives, and its response). Nothing is redacted: the demo's credentials are demo/demo.

**Why:** the run history is the evidence store, and a bot's identity is its profile, so comparing profiles is comparing bots' runs, with no new tables or UI. The bots are always registered, with no flag, because hiding them would add a setting and a second code path. The signals are captured for every profile so a block can be compared with what the browser looked like.

**Cost we accept:** more bots in the list. The capture reads every watched request body (`create`, `login` and `answer`), so the login's password is stored. A failed decode of either body is noted in the event and never fails the run.

**Not verified:** nothing here has run against demo.arcaptcha.co. The tests use the fake page, so they show the mechanism works (flags, script, events), not that any profile reduces blocking. The real request body may arrive in a form Chrome does not put in the network event; the code then falls back to `Network.getRequestPostData`, and records a note if that fails too.

#### Bonus (b): two profiles, a batch runner and a report page

*Later replaced: the report is now `/stats` and the batch flags changed, see "Stats page replaces the bonus report" below.*

**What:**

- **`no-cdc`** runs an `init_script` that deletes chromedriver's `cdc_` properties from `window` before page scripts run. **`webgl-fix`** adds `--enable-unsafe-swiftshader`, so headful Chrome gets a WebGL context. Each is one change from the baseline; a combined profile comes after measuring.
- **Batch runner:** `docker compose run --rm web python -m botplatform.batch --profiles baseline,no-cdc --modes headless --runs 10` (also `--pause`, `--jitter`, `--run-timeout`, `--stop-after`, `--seed`). It queues runs with `queue.enqueue`, the same code the launch endpoint uses, waits for each, prints one line and pauses. The order of all (bot, mode) runs is shuffled, and the seed is printed so an order can be repeated. A combination that is blocked with `captcha_blocked` 5 times in a row is skipped for the rest of the batch (`--stop-after 0` turns this off); its finished runs still count. Ctrl-C prints a summary; a run already queued is left to the worker.
- **Report:** `/bonus` (and `/bonus.md`, generated Markdown with the same `?since=` and `?bot=` filters) shows per bot and mode the outcomes, the `create` captcha types, the not-blocked count with a 95% Wilson interval, runs with a challenge ID and successes. Runs with a `viewer_connected` event are left out of the numbers and counted in the header.

**Why:** probing goes through the platform, so a batch run is an ordinary run and the history is the evidence store. No new tables or migrations. Pauses are short (10s plus up to 5s) because a run takes about 12s, so the whole batch is quick. The order is shuffled so that time of day or a drifting IP reputation cannot favour one profile. The early stop saves runs and goodwill when a profile is plainly still blocked.

**"Not blocked"** means the first `create` response had a captcha type other than `block`. The rate divides by the runs whose first `create` response had a type. Runs with no answer count in the table but not in the rate, so a crashed run is not read as a block or as a pass.

**What I measured (Chrome 156.0.8078.80 in the worker image, no run against the real site):**

- *no-cdc:* the seven `cdc_adoQpoasnfa76pfcZLmcfl_*` properties exist on `window` before page scripts run. They are plain, writable, configurable properties, and the init script (which runs after chromedriver sets them and before the page) removes all seven. They stay gone through a reload and a new navigation, and a later `execute_script` does not bring them back. So the patched chromedriver fallback was not needed. Before: 7 properties; after: 0, both in the page's own early script and in `browser_signals.automation_properties`.
- *webgl-fix:* headful, baseline: `getContext('webgl')` is null. These flags were tried alone, headful: `--enable-unsafe-swiftshader`, `--use-angle=swiftshader` and `--use-gl=angle --use-angle=swiftshader` each give vendor `Google Inc. (Google)` and renderer `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)...`, the same as headless. `--ignore-gpu-blocklist` gives a Mesa llvmpipe renderer instead. `--enable-webgl` and `--in-process-gpu` change nothing. We use `--enable-unsafe-swiftshader`, the smallest set that works. Headless is unchanged by it.

**`all-signals`** combines `stealth-flags`, `no-cdc` and `webgl-fix` (built from their fields, so they stay in sync). **Why:** the 16-run live smoke batch on 2026-11-04 blocked every run, 16/16, for all single-factor profiles, each of which fixed only its own signal. The site may need all of them fixed at once. It is a combined profile, so it cannot say which factor matters.

**`all-signals-headless`** is `all-signals` plus the headful user agent (no `HeadlessChrome`, also in `navigator.appVersion`) and a 1280x800 window and screen. **Why:** live runs on 2026-11-04 from one IP gave `puzzle` in headful 11/11 with `all-signals` but `block` in headless 11/11, and these are what headless still sent differently. **Measured** in headless on the fake page: baseline reports `HeadlessChrome/156.0.0.0`, screen 800x600, window 780x580 outer and 780x437 inner. With `--user-agent` and `--window-size=1280,800` the user agent and window are right (inner 1280x657, outer 1280x800) but the screen stayed 800x600; adding `--screen-info={1280x800}` made it 1280x800. In headful the same arguments change nothing (screen 1280x800, inner 1279x656, as before). The user agent string is a constant that must follow the pinned Chrome version. **Not verified:** that the site stops blocking; the real `create` request has not been checked for other headless differences; and which of the two changes (user agent or screen) matters is not known, because they are in one profile.

**Cost we accept:** a batch of 80 runs takes about 20 minutes. Batch runs fill the history, and the report is the only place that separates them from other runs. A SwiftShader WebGL is still a software renderer, which a detector may know.

**Not verified:** nothing has run against demo.arcaptcha.co, so we do not know that either profile lowers the block rate. The init script removes the properties from the page's `window`; we have not checked that the site reads no other trace of chromedriver (for example on `document`). The batch end-to-end test uses a stand-in worker that finishes runs in the database, not Chrome. The report page has only been tested against seeded runs.

#### Bonus (c): the assisted bot (removed)

The assisted bot (`arcaptcha-assisted`) and the drag probe (`arcaptcha-drag-probe`) were removed in the bots refactor because the solver bots replaced them. Their findings stay in `evidence/` and in git history.

### Solver core: two automatic solver bots

**What:** `arcaptcha-solver-cv-linear` and `arcaptcha-solver-cv-eased` (built headful only with profile `all-signals`; headless was added afterwards, see the mode bullet below). Each finds the gap with the `cv` finder, drags the handle there with Selenium `ActionChains` and lets the login judge. Code: `botplatform/solver/` (`gap.py` finders, `movement.py` paths and the executor, `detect.py` the gap detection) and `bots/arcaptcha/solver.py` (`SliderSolver`, the bot's `Challenge`). Up to 3 answers per run; a verified login is `success`/`solved`, 3 rejected answers `blocked`/`solve_failed`, no gap found `blocked`/`gap_not_found`.

**Facts from live data this rests on:** the background is 260x160 and the piece a separate 50x50 PNG; the handle's `left` equals the piece's `left` equals the answer, 1:1, clamped at 196 px; the right answer is the gap body square's left x minus 10; 3 of 3 drags landing exactly there were accepted (1 Selenium, 2 CDP), drags 10 px or more away were rejected, humans were accepted up to 4 px off; a wrong answer brings a new puzzle in about 0.5 s and 8 wrong answers in a row were not blocked.

**Decisions and reasons:**

- **Vendored CV, trimmed, bytes in and out.** `detect.py` is derived from the captcha-solve project's `detect.py` and `geometry.py`, cut down to the one thing the solver uses: the left edge of the gap's body square. The rest (knobs, corners, centres, contours) was removed as unused code. `gap.py` decodes the bytes in memory (no temp files). **Why:** the submission must build from this repository alone, with no cross-repository dependency, and unused code is only more to read. Because it was trimmed it is no longer a verbatim copy, so taking a change from captcha-solve is now a manual job. OpenCV is an optional extra (`solver`), installed in the worker and test images only, so the web and migrate images stay small.
- **Swappable finder.** A finder is `find_gap_x(background_png, piece_png, piece_top) -> int` registered by name in `FINDERS`; a bot is `arcaptcha-solver-<finder>-<mover>`. **Why:** a different method can then be compared fairly, with the same movement, retries and events. A finder raises `GapNotFound` for no gap or a target outside 0..196.
- **Selenium `ActionChains` for the drag.** **Why:** live data showed Selenium and CDP events are both `isTrusted: true` and both were accepted, so the simpler path is enough. One motion: move to the handle centre, press, move, release, with no second grab.
- **Two movement shapes.** `linear` is 8 equal steps over about 0.6 s (the shape proven live). `eased` is 25-40 steps with an ease-out speed profile over 0.8-1.5 s, a 1-2 px vertical wobble and no overshoot. **Why:** we do not know how sensitive the site is to movement, and the run history can now compare them.
- **No closed loop.** **Why:** the handle-to-piece mapping is exact, so there is nothing to correct after the press. The only check is that the handle moved after the first step; if it did not, the bot releases and presses again on the same puzzle (2 times at most, not counted as an attempt), because once a first drag did nothing while the widget was not ready.
- **3 attempts per run.** **Why:** a wrong answer is cheap (a new puzzle in 0.5 s, 8 in a row were not blocked) but the run has a 180 s limit and an unlimited loop would hide a broken finder. A run reports the attempt number in `solve_attempt`.
- **No gap means the run ends.** The bot does not guess or send a deliberately wrong answer. **Why:** failures are then counted honestly as `gap_not_found`, separate from answers the site rejected. The normal login step still runs, as for every other early result, and cannot change the result.
- **Headful and headless, each with its own profile.** The bots first ran headful only, because at that time only headful with `all-signals` got a puzzle (headful 11/11 puzzle, plain headless 11/11 block). Later the bonus work showed `all-signals-headless` also gets a puzzle in headless (10/10), so the four bots list both modes: a bot picks the profile from the run's mode (`profile_for(mode)`: headful `all-signals`, headless `all-signals-headless`), and a profile passed in by a test wins. **Why:** a headless run is cheaper and needs no display, and the live comparison showed the solver works in both.
- **Longer wait for the first puzzle.** `StepTimeouts.puzzle_ready` is 20 s. **Why:** the first puzzle's images came late (the 5 s capture timed out in 2 of 5 runs). The solver reuses the bytes the capture fetched in the page; a puzzle it cannot capture ends the run as `timeout`/`puzzle_ready`.

**Rejected alternative:** rebuilding each background by taking the per-pixel mode over about 100 samples per background type and subtracting it. It is simpler, but fragile (it breaks with any new background) and needs reference data shipped with the code.

**Live result:** the `cv` bots solved 16 of 16 live runs on attempt 1 (6 in a smoke batch, 10 in the comparison below). The fake demo accepts an answer equal to a known target, so the tests show our own logic; the live runs are what show the site accepts these paths. See the next section and `evidence/solver/results-headful-2x2.md`.

### Stats page replaces the bonus report

**What:** `/bonus`, `/bonus.md`, their `?since=` and `?bot=` filters and the `create` captcha type columns are gone. `/stats` shows, for each bot and mode, the finished runs by status, the success rate with a 95% Wilson interval, and the runs a person watched. Runs with a `viewer_connected` event are left out of the rate and counted only as watched. The batch runner now takes `--bots` (bot ids) instead of `--profiles`, so it can run the solver bots, and loses `--jitter`, `--stop-after` and `--run-timeout`. All eleven bots are kept.

**Why:** the bonus report measured whether the first `create` answer was a block. Now that the solver bots finish the login, the measure that matters is verified success, and the report was built around the question that has been answered. The batch had grown extras (jitter, early stop) that repeating a measurement does not need, and it could not run the solver bots at all. All eleven bots are kept by the user's decision, so every recorded comparison can still be re-run, at the cost of a longer list on `/bots`.

**Cost:** the page no longer tells why a run was blocked, only that it was; the reason is on each run's page. Old links to `/bonus` return 404. The evidence files record results made with the old report and flags.

### Redaction removed: passwords are stored and shown

**What:** the redaction of exception text, the blanking of the password field before screenshots and the rule that login request bodies are never captured are gone. An exception now propagates from the bot and the worker stores its traceback as is. Every request body the watcher sees, login included, is read and recorded as a `login_request`, `create_request` or `answer_request` event. Runs stored before this change keep a `login_response` event instead of `login_request`.

**Why:** the bots use the demo's public login (`demo`/`demo`, printed on its login page) and the web port is bound to 127.0.0.1. Redaction protected nothing, and it garbled tracebacks, because every "demo" became `[password]`.

**Cost we accept:** a real password given in `ARCAPTCHA_PASSWORD` would be stored in the database and visible on run pages, in events and in screenshots. Use only the demo account.

### Solver: the silhouette finder and the 2x2 comparison

**What:** a second finder, `silhouette` (`find_gap_x_silhouette` in `botplatform/solver/gap.py`), and two more bots, `arcaptcha-solver-silhouette-linear` and `arcaptcha-solver-silhouette-eased` (same headful / `all-signals` setup). With the two `cv` bots the four bots are a 2x2 of finder x movement for the live comparison.

**Method:** one-dimensional silhouette matching. The piece's row (`piece_top`) and exact shape (its alpha channel, pixels above 128) are known, so only x is unknown. For each x in 0..196 the score is the mean brightness of a thin ring (about 2 px) just outside the silhouette, minus the mean brightness inside it, using `cv2.matchTemplate` on the grayscale strip of the background. The answer is the best x. It raises `GapNotFound` if the best score is under 40 gray levels or does not beat every x at least 8 px away by 20. About 60 lines, OpenCV and numpy only, bytes in memory.

**Why it is a useful comparison:** it is an independent method. It does not use `find_piece_mask` or `body_left`, so it does not depend on the halo detector or on the "body square minus 10" rule. It needs no reference data. It uses the piece image, which the `cv` finder ignores. If the two finders agree on a puzzle that is good evidence for both; if they disagree, the live result shows which one the site accepts.

**Choice of score:** four simple scores were tried on the 8 fixtures before any bot was registered: edge strength along the outline, ring minus inside, a wider ring minus inside, and ring minus wider ring. The first two were exact on 8 of 8 (the others were off by up to 2 px). Ring minus inside was kept because it follows what the gap looks like (light halo, dark interior). No tuning beyond that.

**Offline comparison with the fixtures** (`cv_target` is the other finder's answer; "score" is the best ring-minus-inside, "lead" is its margin over the best x at least 8 px away):

| fixture | silhouette | cv_target | human | diff cv | diff human | score | lead |
|---|---|---|---|---|---|---|---|
| 578370f1 | 60 | 60 | 58 | 0 | +2 | 133.5 | 96.8 |
| 6c3cc0fd | 90 | 90 | 90 | 0 | 0 | 138.2 | 81.9 |
| 75d5e12d | 100 | 100 | 101 | 0 | -1 | 119.1 | 93.2 |
| c11962fb | 130 | 130 | 131 | 0 | -1 | 131.9 | 101.1 |
| c5dc69eb | 170 | 170 | 166 | 0 | +4 | 151.0 | 105.8 |
| de3139ec | 170 | 170 | 169 | 0 | +1 | 152.4 | 104.4 |
| f0af6952 | 100 | 100 | 101 | 0 | -1 | 161.3 | 100.9 |
| f667f20b | 130 | 130 | 128 | 0 | +2 | 136.1 | 85.6 |

Exact match with `cv_target`: 8 of 8; largest difference 0 px; within 4 px of cv_target 8 of 8, within 9 px 8 of 8. Against the human answers the largest difference is 4 px. Both background types are among the fixtures and neither failed. The thresholds sit far from both sides: real puzzles scored 119..161 with a lead of 82..106, while blank, smooth, gradient and random-noise backgrounds scored at most 7.2 with a lead under 0.5.

**Known limits:** the fixtures are only 8 puzzles, and the `cv_target` is the other finder's answer, not the site's, so agreement shows consistency, not correctness. The method relies on the halo being brighter than the gap interior; a background with a very bright interior, or a gap whose halo is lost in a bright area, could fail or pick another place, and it would then rather answer wrongly with a high score than raise. It needs the piece's row and alpha to be right (a piece with no alpha or a row outside the image raises `GapNotFound`). The accepted tolerance of the site is under 10 px; this finder is exact on the fixtures, but that is the same data the method was chosen on.

**Live results (headful, 2026-11-04):** the 2x2 was run interleaved, 10 rounds of the four bots, 40 runs in all. Every run ended `success` / `solved` and every run was solved on attempt 1: 10 of 10 for each of `cv-linear`, `cv-eased`, `silhouette-linear` and `silhouette-eased`. Median run 15.7 to 16.0 s; drag time 0.6 s (linear) against about 1.2 s (eased). The runs covered 13 different gap positions. Table, method and per-run rows: `evidence/solver/results-headful-2x2.md` and `runs-headful.json`.

**Headless:** the same 2x2 was then run in headless mode with the `all-signals-headless` profile: another 40 of 40 `success` / `solved`, all on attempt 1 (medians 14.7 to 16.3 s). See `evidence/solver/results-headless-2x2.md` and `runs-headless.json`. Together that is 80 of 80 runs.

**What the comparison can and cannot say:** both finders are accepted by the site, so the silhouette method is a valid independent second method. Neither finder nor movement shape changed acceptance. With no failures in 40 runs per mode, the true failure rate is only bounded (probably below about 7% per mode, about 4% over all 80), and the four bots cannot be ranked. One IP and one evening for both modes: another IP or time of day may differ. The fake demo checks only that the answer equals a known target for one fixture.

**Reaction to a challenge is a strategy.** A bot's reaction to a challenge is a strategy object (`Challenge`) on its spec, so a bot for another challenge type is a new class, not a flag. The default, `GiveUp`, ends the run as `blocked` / `challenge_unsolved`.

## Linting and type checking

CI runs ruff (its default rules plus `UP031`, `UP032` and `G`) and pyright in standard mode over `src`, `tests` and `migrations`. The code has no `type: ignore` comments. Log calls keep `%s` arguments so that the message is built only if the record is emitted, and ruff's `G` rules enforce this. f-strings are used everywhere else.

## Platform support

amd64 only. ARM64 was not considered, and the README states this limitation.

## Meaning of a blocked run

A blocked run is a failed run, even when `challenge_id` was recorded, because the required scenario also includes logging in and verifying the result. The run stays visible in the history with its `challenge_id`.

**Not confirmed:** this is our own reading of the PDF. We plan to ask ARCaptcha whether a blocked run with a recorded `challenge_id` counts as completing the workflow.
