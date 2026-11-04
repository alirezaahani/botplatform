# Bonus report: blocked or not

- Generated at: 2026-11-04 10:37:15 UTC
- Filters: since none, bot arcaptcha-all-signals-headless
- Every recorded run that matches the filters is included, except runs with a `viewer_connected` event (a person may have helped): 0 excluded
- "Not blocked": The create request was answered with any captcha type other than "block". The rate is not blocked runs divided by runs whose create answer has a type. Runs with no answer or no type ("none") are counted in the table but not in the rate. Interval: 95% Wilson.

| Bot | Mode | Runs | Outcomes | create types | Not blocked | Rate (95% CI) | With challenge ID | Success | Excluded |
|---|---|---|---|---|---|---|---|---|---|
| arcaptcha-all-signals-headless | headless | 10 | blocked/challenge_unsolved 10 | puzzle 10 | 10 of 10 | 100% (72% to 100%) | 10 | 0 | 0 |

## Notes (added by hand)

- Same IP as before, 2026-11-04. Batch: `python -m botplatform.batch --profiles all-signals-headless --modes headless --runs 10 --stop-after 0 --seed 5 --pause 5 --jitter 3`.
- `all-signals-headless` (all-signals plus a `Chrome` user agent and a 1280x800 screen and window) in headless mode: `captcha_type: puzzle` in every run, each with its own `challenge_id`. Compare `all-signals` headless: `block` 11 of 11 (`results-ip1-all-signals-headless.md`).
- Nothing solved the puzzle, so each run ends `blocked/challenge_unsolved`.
- These 10 runs were not interleaved with other profiles, so time of day is not controlled. Which of the two added changes (user agent or screen size) matters is not known.
