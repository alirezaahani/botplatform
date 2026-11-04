# Solver bots, headless: the 2x2 comparison

The same four solver bots as in [results-headful-2x2.md](results-headful-2x2.md), run in `headless` mode. In this mode each bot uses the `all-signals-headless` browser profile (the headful runs used `all-signals`). One IP, on 2026-11-04 (late evening), the same day and network as the headful batch. Per-run rows are in [runs-headless.json](runs-headless.json); every run's record holds the profile it used (`browser_profile` event, name `all-signals-headless` in all 40).

| Bot | Finder | Movement | Runs | `success` / `solved` | Solved on attempt 1 | Median run | Drag time (average) |
|---|---|---|---|---|---|---|---|
| `arcaptcha-solver-cv-linear` | `cv` | 8 equal steps | 10 | 10 | 10 | 15.2 s | 0.60 s |
| `arcaptcha-solver-cv-eased` | `cv` | ease-out, 25-40 steps | 10 | 10 | 10 | 16.0 s | 1.09 s |
| `arcaptcha-solver-silhouette-linear` | `silhouette` | 8 equal steps | 10 | 10 | 10 | 14.7 s | 0.60 s |
| `arcaptcha-solver-silhouette-eased` | `silhouette` | ease-out, 25-40 steps | 10 | 10 | 10 | 16.3 s | 1.17 s |

"Run" time is from the start of the run to its end, including the page, the checkbox, the solve and the login. "Success" means a verified login after the answer.

## How the runs were made

Exactly like the headful batch: 10 rounds, in each round one run of each bot in the order `cv-linear`, `silhouette-eased`, `cv-eased`, `silhouette-linear`, 15 seconds between runs, started through the platform's launch endpoint with `mode=headless`.

## What the runs show

- All 40 runs ended `success` / `solved`, all on the first attempt: no rejected answers, no stuck handle and no failed puzzle capture.
- The 40 runs covered the same 13 gap positions as the headful batch (60 to 180 px in steps of 10).
- Headless behaved like headful for all four bots: the puzzle appeared every time, the drag moved the handle, and the answer was accepted. Run times are similar (medians 14.7 to 16.3 s here, 15.7 to 16.0 s headful).
- Taken together with the headful batch: 80 of 80 runs solved (plus 6 earlier smoke runs, also solved).

## What they do not show

- **No success rate.** 0 failures in 40 runs only says the failure rate in this mode is probably below about 7%; over all 80 runs, probably below about 4% (the "rule of three": 3 divided by the number of runs).
- **No ranking.** With no failures, the four bots still cannot be told apart on acceptance. Neither the finder nor the movement shape mattered here.
- **One IP, one evening.** Another network, time of day or Chrome version may behave differently. The two modes were run on the same evening, so they share any effect of that time.
- **The headless profile is what makes it work.** The earlier bonus work found that the plain baseline bot was blocked in 8 of 8 headless runs and that this profile got a puzzle in 10 of 10 (see [../bonus/README.md](../bonus/README.md)). These runs used that profile; nothing here says what plain headless would do.
- **The tolerance.** The runs landed exactly on the target each time, so they say nothing new about how far off the site still accepts (it accepted humans up to 4 px off and rejected drags 10 px or more off).
