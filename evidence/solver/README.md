# Puzzle capture: data for a slider solver

Every bot that uses the ARCaptcha scenario (not only `arcaptcha-assisted`) captures each puzzle it sees. A failed capture is recorded and never changes the run's result.

## What is captured, per puzzle n (counted from 1 in the run)

- Artifacts `puzzle-<n>-background.<ext>` and `puzzle-<n>-piece.<ext>`. The bytes are fetched by `fetch(src)` inside the page, so the request has the browser's origin and cookies. The extension and content type come from the bytes.
- A `puzzle_captured` event with: `challenge_id` (of the latest `create`), `n`, the artifact names, and for each image its `src`, `natural_width`/`natural_height` and on-screen `rect`. The piece also has its inline `style_left`/`style_top` and `computed_left`/`computed_top`. The event also holds `wrapper_rect` (the background's parent), `piece_parent_rect`, `slider_candidates` and `device_pixel_ratio`.
- If the images do not load in time or the fetch fails, a `puzzle_capture_failed` event with `challenge_id`, `n` and the error type.

## Selectors, as found on the live site

- The piece is `img.puzzle` and the background is the other `img` whose `src` contains `/puzzles/`. Both were captured in live runs.
- The slider handle is `div.draggable` (64x40 px, starts at `left: 0` under the 260x160 image). `slider_candidates` found it in every live capture. The press lands on the arrow element inside it.

## Pairing a puzzle with its answer

Pair an answer with its puzzle by `challenge_id`: `puzzle_captured.challenge_id` equals `answer_request.request.challenge_id`. Do not pair by event order, because a fast answer can be logged before the capture of the same poll. The `answer` record is unchanged: `request.answers` is the slider x and `response.success` is the label (true means the position was right).

## Making labeled samples from assisted runs

1. Run `arcaptcha-assisted` and solve the slider by hand.
2. For each `puzzle_captured` n, take the next `answer_request`: `answers` is the slider x, `success` says whether it was right.
3. A sample is (background image, piece image, piece `top`, `answers`). Rows with `success: true` are positive labels. A `false` row only says that x was wrong.
4. The slider x, the handle's `left` and the piece's `left` are the same number (1:1, no scale or offset), so `answers` can be used directly. The handle stops at 196 px.

## The drag probe experiment (`arcaptcha-drag-probe`)

An experiment, not a solver. Headful, profile `all-signals`. It ticks the checkbox and, if a puzzle appears, makes up to 8 attempts (limit and a 100 s budget are in `StepTimeouts`), one per puzzle. Attempt i uses method `selenium` (ActionChains press, 8 moves, release) when i is even and `cdp` (`Input.dispatchMouseEvent`) when odd, with dx 40, 80, 120, 150, 180, 200, 240, 300 px (the last ones over-travel on purpose). Puzzle n is captured before attempt n's drag. The answer is never read to decide anything, except that `success: true` is recorded and ends the probe. The run always ends `blocked` / `drag_probe_done`, never as a solve. Then the normal login runs, as for every bot.

Events: `drag_probe_started` (plan), `drag_probe_attempt` per attempt, `drag_probe_failed` (type, message; the probe goes on, and stops after two failures in a row), `drag_probe_finished` (`reason`: `plan_finished`, `budget_spent`, `answer_accepted`, `no_answer`, `no_new_puzzle`, `repeated_failures`, `no_puzzle`). The `answer_request` events are recorded as usual.

A `drag_probe_attempt` holds `n`, `challenge_id`, `method`, `dx`, `error`, `outcome` (`next_puzzle`, `no_answer`, `no_new_puzzle`), `samples`, `after_outcome` (state once the answer and next puzzle arrived, so usually the new puzzle) and `listener`. Each sample (`before`, `pressed`, 8 x `step`, `released`; `moved` is the requested px) has `handle`, `piece` and `piece_parent`, each with `rect`, inline `style_left`/`style_transform` and `computed_left`/`computed_transform`.

How to read it:

- Ratio handle to piece: for the `released` sample, (piece `computed_left`) / (handle `computed_left`), or the rect `x` change of each. Check it at several dx, and at the over-travel ones for the clamp of each (about 196 px for the handle was seen).
- `answers`: pair `answer_request.request.answers` with the attempt by `challenge_id`. Compare it to the piece's final left, the handle's final left, and `dx`. If the handle did not move (`released` equals `before`), the widget ignored that method.
- Event family: `listener` counts, per event type, `count`, the first 5 `isTrusted` values and the first 3 targets. Mouse, pointer, touch or drag types with counts above zero show what reached the page; this says what the widget could listen to, not what it does. Look at `targets` for the element receiving the press.
- Trusted: `isTrusted` false for an event type means the browser marked it synthetic. CDP and WebDriver input normally give true.

Live results (2026-11-04): both methods moved the real handle, the handle's and the piece's `left` always matched `dx` exactly up to a clamp at 196 px, and the widget listens to mouse and pointer events (both `isTrusted: true`) on the arrow element inside the handle. Three drags that landed exactly on the gap were accepted (one Selenium, two CDP) and every drag 10 px or more away was rejected.

## Reading `solve_attempt` events (`arcaptcha-solver-<finder>-<mover>`)

The four solver bots are `arcaptcha-solver-cv-linear`, `arcaptcha-solver-cv-eased`, `arcaptcha-solver-silhouette-linear` and `arcaptcha-solver-silhouette-eased` (finder x movement). The `finder` field of `solve_attempt` says which finder gave the target.

The automatic solver records `solve_started` (finder, mover, attempt cap, stuck retries, `puzzle_ready`), one `solve_attempt` per answer it makes, and `solve_finished` (`reason`: `solved`, `solve_failed`, `gap_not_found`, `not_a_puzzle`, or a step name such as `puzzle_ready` when it timed out).

A `solve_attempt` has:

- `n` (attempt in the run, from 1), `puzzle` (the capture number) and `challenge_id`. Pair it with `puzzle_captured` and `answer_request` by `challenge_id`.
- `finder`, `target_x` (what the finder returned, also the dx) and `mover`, `duration` (seconds of planned path) and `steps`.
- `stuck_retries`: how many times the handle did not move after the first step and was pressed again on the same puzzle. These do not add to `n`.
- `handle_left` and `piece_left`: read just before the release. Both should equal `target_x`; a difference means the drag fell short.
- `outcome`: `accepted` (an answer and no new puzzle within `answer_settle`), `rejected` (an answer and then a new puzzle), `no_answer` (no answer request arrived), or `gap_not_found` (no drag was made; `target_x` is null). The final judge is still the login: a run is `success`/`solved` only if the login verified.
- `error` when the drag raised.

To compare finders or movements, group runs by bot id and count the `accepted` attempts over all attempts, and look at `n` of the accepted one. The live results so far are in [results-headful-2x2.md](results-headful-2x2.md), with per-run rows in [runs-headful.json](runs-headful.json).

