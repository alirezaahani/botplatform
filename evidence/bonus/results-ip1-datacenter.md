# Bonus report: blocked or not

- Generated at: 2026-11-04 10:11:31 UTC
- Filters: since none, bot all
- Every recorded run that matches the filters is included, except runs with a `viewer_connected` event (a person may have helped): 1 excluded (arcaptcha-webgl-fix headful 1)
- "Not blocked": The create request was answered with any captcha type other than "block". The rate is not blocked runs divided by runs whose create answer has a type. Runs with no answer or no type ("none") are counted in the table but not in the rate. Interval: 95% Wilson.

| Bot | Mode | Runs | Outcomes | create types | Not blocked | Rate (95% CI) | With challenge ID | Success | Excluded |
|---|---|---|---|---|---|---|---|---|---|
| arcaptcha | headful | 7 | blocked/captcha_blocked 7 | block 7 | 0 of 7 | 0% (0% to 35%) | 7 | 0 | 0 |
| arcaptcha | headless | 8 | blocked/captcha_blocked 8 | block 8 | 0 of 8 | 0% (0% to 32%) | 8 | 0 | 0 |
| arcaptcha-all-signals | headful | 1 | blocked/challenge_unsolved 1 | puzzle 1 | 1 of 1 | 100% (21% to 100%) | 1 | 0 | 0 |
| arcaptcha-all-signals | headless | 1 | blocked/captcha_blocked 1 | block 1 | 0 of 1 | 0% (0% to 79%) | 1 | 0 | 0 |
| arcaptcha-no-cdc | headful | 2 | blocked/captcha_blocked 2 | block 2 | 0 of 2 | 0% (0% to 66%) | 2 | 0 | 0 |
| arcaptcha-no-cdc | headless | 5 | blocked/captcha_blocked 5 | block 5 | 0 of 5 | 0% (0% to 43%) | 5 | 0 | 0 |
| arcaptcha-stealth-flags | headful | 3 | blocked/captcha_blocked 3 | block 3 | 0 of 3 | 0% (0% to 56%) | 3 | 0 | 0 |
| arcaptcha-stealth-flags | headless | 4 | blocked/captcha_blocked 4 | block 4 | 0 of 4 | 0% (0% to 49%) | 4 | 0 | 0 |
| arcaptcha-webgl-fix | headful | 6 | blocked/captcha_blocked 6 | block 6 | 0 of 6 | 0% (0% to 39%) | 6 | 0 | 1 |
| arcaptcha-webgl-fix | headless | 4 | blocked/captcha_blocked 4 | block 4 | 0 of 4 | 0% (0% to 49%) | 4 | 0 | 0 |

## Notes (added by hand)

- IP: the developer's data center IP, the same one used for every earlier run. Chrome for Testing 156 in the worker image.
- This is the export of `/bonus.md` after the 16-run smoke batch (seed 1), one extra headful run started by hand to test the live viewer (it is the excluded run), and a matrix batch (seed 2, 100 runs planned) that was **stopped by hand after about 19 runs** because nearly everything was blocked. Rows are unequal in size for that reason, so the rates are not comparable between rows.
- The one run that was not blocked at `create` is `arcaptcha-all-signals` headful, run `43bdbbb4-d02f-4a47-a81e-09396cb09c1f`: the server answered `captcha_type: puzzle` and a `challenge_id`. Nothing solved the puzzle, hence `blocked/challenge_unsolved`, and the login step failed with `ElementNotInteractableException` because the puzzle popup covered the form. It is 1 run, and the 95% interval is 21% to 100%. It needs repeating before it counts as evidence.
