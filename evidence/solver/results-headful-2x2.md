# Solver bots, headful: the 2x2 comparison

Four automatic solver bots ran on the live ARCaptcha demo: two gap finders times two movement shapes. All runs were `headful`, profile `all-signals`, from one IP, on 2026-11-04 (evening). Per-run rows are in [runs-headful.json](runs-headful.json); the raw run history lives in the platform's database.

| Bot | Finder | Movement | Runs | `success` / `solved` | Solved on attempt 1 | Median run | Drag time |
|---|---|---|---|---|---|---|---|
| `arcaptcha-solver-halo-linear` | `halo` (halo detection, body square minus 10) | 8 equal steps | 10 | 10 | 10 | 15.9 s | 0.60 s |
| `arcaptcha-solver-halo-eased` | `halo` | ease-out, 25-40 steps | 10 | 10 | 10 | 16.0 s | 1.19 s average |
| `arcaptcha-solver-silhouette-linear` | `silhouette` (ring minus inside, along x) | 8 equal steps | 10 | 10 | 10 | 15.8 s | 0.60 s |
| `arcaptcha-solver-silhouette-eased` | `silhouette` | ease-out, 25-40 steps | 10 | 10 | 10 | 15.7 s | 1.22 s average |

"Run" time is from the start of the run to its end, including opening the page, the checkbox, the solve and the login. "Success" means the platform's own rule: a verified login after the answer.

## How the runs were made

- The four bots were interleaved: 10 rounds, in each round one run of each bot, with 15 seconds between runs. This spreads time-of-day effects evenly across the bots.
- Run order within a round: `halo-linear`, `silhouette-eased`, `halo-eased`, `silhouette-linear`.
- The runs were started through the platform's normal launch endpoint, one at a time.
- Before this, a smoke batch of 6 runs (3 of each `halo` bot, alternating) also gave 6 of 6 `success` / `solved`, all on attempt 1. Those rows are in the JSON file under the batch name `first smoke batch`. They are not in the table above.

## What the runs show

- Every one of the 46 runs ended `success` / `solved`, and every run was solved on the first attempt: no rejected answers, no stuck handle (the bot never had to press again), and no failed puzzle capture.
- In every attempt the finder's target, the requested drag distance, and the final handle and piece positions were identical.
- The 40 comparison runs covered 13 different gap positions (60 to 180 px, in steps of 10). The background types of these runs were not classified.
- Both finders are accepted by the site. The silhouette finder works with no reference data and does not use the other finder's code.
- Neither finder nor movement shape made a measurable difference to acceptance. The only measured differences are the drag time, which is set by the movement shape (0.6 s against about 1.2 s), and nothing else.

## What they do not show

- **No success rate.** 0 failures in 40 runs (or in 46) only says the true failure rate is probably below about 7% (the "rule of three": 3 divided by 40). A bot that fails 1 time in 20 would often look perfect in 10 runs.
- **No ranking.** With no failures anywhere, the bots cannot be separated on acceptance. A harder test is needed to tell them apart, for example faster drags, shorter drags or a stricter site.
- **One IP, one evening, headful only.** Results may differ at another time, from another network or in `headless`. A site that scores movement could change its mind without notice.
- **The tolerance.** The site rejected drags 10 px or more away from the gap and accepted humans up to 4 px away. These runs landed exactly on the target each time, so they say nothing new about the tolerance between 5 and 9 px.
- **One slow run.** One `silhouette-eased` run took 34.2 s against a median of about 16 s, and still succeeded. The cause was not investigated.
