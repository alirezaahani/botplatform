# Bonus report: blocked or not

- Generated at: 2026-11-04 10:16:45 UTC
- Filters: since none, bot arcaptcha-all-signals
- Every recorded run that matches the filters is included, except runs with a `viewer_connected` event (a person may have helped): 0 excluded
- "Not blocked": The create request was answered with any captcha type other than "block". The rate is not blocked runs divided by runs whose create answer has a type. Runs with no answer or no type ("none") are counted in the table but not in the rate. Interval: 95% Wilson.

| Bot | Mode | Runs | Outcomes | create types | Not blocked | Rate (95% CI) | With challenge ID | Success | Excluded |
|---|---|---|---|---|---|---|---|---|---|
| arcaptcha-all-signals | headful | 11 | blocked/challenge_unsolved 11 | puzzle 11 | 11 of 11 | 100% (74% to 100%) | 11 | 0 | 0 |
| arcaptcha-all-signals | headless | 1 | blocked/captcha_blocked 1 | block 1 | 0 of 1 | 0% (0% to 79%) | 1 | 0 | 0 |

## Notes (added by hand)

- Same IP as every earlier run (developer's data center IP), 2026-11-04. Batch: `python -m botplatform.batch --profiles all-signals --modes headful --runs 10 --stop-after 0 --seed 3 --pause 5 --jitter 3`.
- The 11 headful runs are the 1 run from the earlier matrix plus these 10. Every one got `captcha_type: puzzle` and its own `challenge_id` (11 distinct IDs). Nothing solved the puzzle, so each ended `blocked/challenge_unsolved`.
- For comparison on the same IP, headful runs of the other profiles got `block` every time: baseline 7/7, webgl-fix 7/7, stealth-flags 3/3, no-cdc 2/2. Sample sizes differ, and the runs were not interleaved with `all-signals` in this repeat, so time of day is not controlled. The earlier matrix did interleave them.
- Headless `all-signals` is 1 run, blocked. Not enough to say anything.
