# The assisted bot: does the site accept a correct answer?

Seven live runs of `arcaptcha-assisted` on 2026-11-04, from the same data center IP as the rest of the bonus work, using the `all-signals` profile (headful). A person solved the slider with a real mouse through the noVNC viewer, one run at a time. Raw run rows and events are in `runs.json`. The person's notes on how they moved are the only record of the movement: the bot does not capture it.

| Run | How the person moved (their words) | Seconds from puzzle to answer | `answers` | `answer` response | Run result |
|---|---|---|---|---|---|
| 1 | natural | about 12 | 150 | `success: true` | `success` / `human_solved` |
| 2 | natural | about 11 | 92 | `success: true` | `success` / `human_solved` |
| 3 | wiggled back and forth | about 16 | 142 | `success: true` | `success` / `human_solved` |
| 4 | fast, "not really straight" | about 5 | 155 | `success: true` | `success` / `human_solved` |
| 4b | fast, "tried my best, not really straight" | about 2.4 | 173 | `success: true` | `success` / `human_solved` |
| 5 | slow and careful | about 38 | 140 | `success: true` | `success` / `human_solved` |
| 6 | wrong on purpose, then a correct solve | first answer about 25, then about 7 more | 168 (wrong), then 178 | `success: false`, then `success: true` | `success` / `human_solved` |

Run 4b was an extra attempt at a straight drag after the person said run 4 had not been straight. `runs.json` lists the runs in start order, so 4b follows 4.

## What the runs show

- **A correct answer from this browser is accepted end to end.** In every run the login returned HTTP 200 with "You are logged in successfully!" and a green toast. 7 of 7 runs reached a verified login, with a correct answer each time.
- **The `answer` request is small:** `{"answers": <number>, "site_key", "drag_drop": 0, "challenge_id", "drag_drop_time": <timestamp in ms>}`. `answers` is the slider position and differs per puzzle (92 to 178 here). `drag_drop` was 0 in every run, and we do not know what it is for. `drag_drop_time` is a timestamp, not a duration.
- **The response is `{"success": true|false}` with HTTP 200 either way.** A rejected answer is not an HTTP error.
- **A rejection brings a new puzzle at once.** In run 6 the wrong answer (168) got `success: false`, and a new `create` with a new `challenge_id` followed within about 0.5 seconds. The next puzzle was again `puzzle`. Both `challenge_id`s were recorded (the run keeps the latest, the earlier one is in its events). The second answer (178) was accepted, and login worked with the second ID.
- **The 3-second "puzzle finished" rule held in every run:** after an accepted answer no new `create` arrived.
- **Speed and style did not matter** in this range: answers from about 2 to about 38 seconds were accepted, with clean, wiggly and fast movements.

## What this does not show

- **Straightness.** None of the runs had a straight drag (the person tried twice and said it was not straight), so we know nothing about linear movement from this experiment.
- **Synthetic input.** A person moved a real mouse. A Selenium drag arrives through different events, and the site may rate it differently. It has to be tested with the solver.
- **Rates.** 7 runs by hand say nothing about how often the site would accept an automated answer.
- **The mouse verdict.** The request to `lab.arcaptcha.co/mouse/api/store` was not captured, so we cannot see how the site rated the movement.
- **Other IPs.** Same IP as every other run.
