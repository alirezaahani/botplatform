# Bonus report: blocked or not

- Generated at: 2026-11-04 10:22:25 UTC
- Filters: since none, bot arcaptcha-all-signals
- Every recorded run that matches the filters is included, except runs with a `viewer_connected` event (a person may have helped): 0 excluded
- "Not blocked": The create request was answered with any captcha type other than "block". The rate is not blocked runs divided by runs whose create answer has a type. Runs with no answer or no type ("none") are counted in the table but not in the rate. Interval: 95% Wilson.

| Bot | Mode | Runs | Outcomes | create types | Not blocked | Rate (95% CI) | With challenge ID | Success | Excluded |
|---|---|---|---|---|---|---|---|---|---|
| arcaptcha-all-signals | headful | 11 | blocked/challenge_unsolved 11 | puzzle 11 | 11 of 11 | 100% (74% to 100%) | 11 | 0 | 0 |
| arcaptcha-all-signals | headless | 11 | blocked/captcha_blocked 11 | block 11 | 0 of 11 | 0% (0% to 26%) | 11 | 0 | 0 |

## Notes (added by hand)

- Same IP as before, 2026-11-04. Batch: `python -m botplatform.batch --profiles all-signals --modes headless --runs 10 --stop-after 0 --seed 4 --pause 5 --jitter 3`.
- `all-signals` headless: `block` in 11 of 11 runs (the 1 earlier run plus these 10), each with its own `challenge_id`. The headful table row in this file is from the earlier repeat (11 of 11 `puzzle`). So the combination helps headful only.
- What headless still sends that headful does not (from `evidence/bonus/audit/README.md`): `HeadlessChrome` in the user agent and app version, an 800x600 screen, and a window of 780x437.
